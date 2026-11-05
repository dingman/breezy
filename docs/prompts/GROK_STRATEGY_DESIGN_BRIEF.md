You are designing NEW trading strategies for "Breezy," an autonomous weather-prediction trading bot built natively on Nautilus Trader (a Python algo-trading framework), trading binary-option weather markets on Polymarket.us. Your job is DESIGN ONLY — architecture, edge hypothesis, and falsification plan. You will never see the codebase; every constraint you need is stated below. Do not write code. Propose exactly THREE strategies, each genuinely distinct in mechanism from the other two and from the FIVE strategies that already exist (`forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`, `cli_settlement_print_lock`, `running_extreme_lock` — described below, so you can prove non-overlap).

======================================================================
PART 1 — THE REAL PLUG-IN CONTRACT (design against this exactly)
======================================================================

A Breezy strategy is a subclass of Nautilus Trader's native `Strategy`
(`nautilus_trader.trading.strategy.Strategy`), configured via a subclass of
`StrategyConfig` (imported from `nautilus_trader.trading.config`, NOT
`nautilus_trader.trading.strategy` — the wrong import breaks construction).
There is no Breezy wrapper or lifecycle abstraction on top of Nautilus.

**File layout convention** (established by three existing strategies —
`forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`,
each under `src/breezy/strategy/<name>/`):
- `config.py` — the frozen `StrategyConfig` subclass (all tunable parameters,
  including `allow_short: bool = False`).
- `decision.py` — PURE function(s) that read market/weather state and return
  a `SignalDecision | None`. No I/O, no order submission here.
- `strategy.py` — the Nautilus `Strategy` subclass: owns `on_start`,
  `on_order_book_depth`, `on_data`, calls the decision function, then passes
  the result through the shared risk layer, then submits the order.

**The decision output contract** — `SignalDecision`
(`src/breezy/strategy/weather_common/models.py`):
```
instrument_id: str
intent: SideIntent            # LONG_YES, SHORT_YES, or FLAT
model_probability: float
market_probability: float
edge: float
conviction: float
quantity: float
reason: str
metadata: Mapping[str, float | str | int | None] = {}
```

**Executable edge is computed against bid/ask, never midpoint**
(`edge_after_costs` in `weather_common/risk.py`):
`Long YES edge = model_p - ask_p - cost`; `Short YES edge = bid_p - model_p - cost`.

**The risk gate every order must clear** —
`RiskManager.evaluate_order(*, contract, signed_qty_delta, hours_to_settlement,
forecast_age_hours, edge, portfolio, quote, quote_age_minutes)` in
`src/breezy/strategy/weather_common/risk.py`, checked in this order:
1. `hours_to_settlement` below `halt_hours_before_settlement` / `min_hours_to_settlement` → refused.
2. `forecast_age_hours` above `stale_forecast_hours` → refused (stale forecast).
3. `abs(edge)` below `min_model_edge` → refused.
4. Any order that would OPEN a short (negative `signed_qty_delta` against settled qty) is refused UNLESS `allow_short=True` — default `False` in every existing strategy.
5. Quote must have live bid AND ask, not crossed, spread within `max_bid_ask_spread`, liquidity >= `min_liquidity_contracts`, and not stale/future — else refused.
6. Exclusive-bucket conflict (can't hold two overlapping long-YES buckets on the same settling event) → refused.
7. `max_position_contracts` per instrument → clipped or refused.
8. `max_event_notional` and `max_location_notional` → refused if exceeded. These are **absolute dollars in MAX-PAYOUT units**: `contract.contract_size` (payout dollars per contract, 1.0 for a binary option) x contracts, grouped by `event_key = "{settlement_station}:{climate_day}"` and `location_id = settlement_station` (`weather_common/bucket_contract.py`). This is NOT market value — reasoning in market value silently blows the cap.
9. `max_simultaneous_positions` → refused if exceeded.
10. `max_equity_fraction` of portfolio equity → clipped.

Only after all of that does the strategy submit a real Nautilus order.

**Four data streams a strategy can subscribe to, and what they actually are:**
- `OrderBookDepth10` — subscribe via `subscribe_order_book_depth`; THIS, not `QuoteTick`, drives execution price under the L2 book model. A strategy that only reads quotes may never trade.
- `QuoteTick` — optional, logging/tracing only.
- `NwsClimateDay` weather records — NOAA/NWS climate-day observations (station, climate_day, `tmax_f`/`tmin_f`/`tavg_f` as `int | None`, `is_final`, `correction_flag`, `revision_seq`, `issuing_office`, timestamps). Delivered via `subscribe_data(..., client_id=NWS_BACKTEST_CLIENT_ID)` — CLIENT-scoped, not instrument-scoped, so every strategy receives every city's records and MUST filter with `WeatherBucketFacts.applies_to(station, climate_day)` (read via `read_weather_bucket_facts(instrument.info)`) or it will size a position off the wrong city's weather.
- `InstrumentClose` — settlement trigger; the harness handles this, a strategy rarely needs the callback directly.

**Backtest harness** (`src/breezy/runtime/backtest_harness.py`,
`BreezyBacktestConfig` / `run_backtest(config, strategies=(...))`,
invoked by `scripts/analysis/run_weather_strategy_backtests.py`): fixed to a
single Polymarket.us venue, NETTING order-management, CASH account,
L2 order-book model, a mandatory venue-specific fee model. Registration
requires ZERO changes to `pyproject.toml` or any `__init__.py` — a strategy
is just a new file, imported by direct name.

======================================================================
PART 2 — HARD CONSTRAINTS (each is load-bearing; design around ALL of them)
======================================================================

1. **LONG-ONLY IS THE ONLY EXECUTABLE DIRECTION.** On Polymarket.us, "NO" is
   a SIDE of the same order book as "YES," not a separate tradable
   instrument — there is no complementary short instrument to sell into.
   Separately, the empirical top-of-book bid on these weather markets is
   almost always absent (median top-of-book bid size is a small fraction of
   one contract) — even where a short is theoretically representable, there
   is no depth to sell into. Consequently the shorts-only
   trap is real and already cost us one strategy. **(Counts corrected
   2026-09-01.)** FIVE strategies exist today, not three:
   `calibration_mean_reversion` is **SHORT_YES-only** and is refused by the
   risk layer's permanent `allow_short=False` before it ever reaches a quote
   check — it does not trade; `forecast_mispricing` and `forecast_revision`
   each have both a LONG and a SHORT branch, so they trade only on their long
   branch; `cli_settlement_print_lock` and `running_extreme_lock` are
   **LONG_YES-only by construction** (`decision.py` has no branch that can
   return `SHORT_YES`) and are the shape to imitate. **Any design whose edge requires
   selling, shorting, or "fading" a YES price upward is dead on arrival.**
   Every proposed strategy's executable path must be expressible entirely
   as BUYING YES (or declining to trade).

2. **BREEZY INGESTS NO FORECAST DATA TODAY.** The only weather feed that
   exists is NOAA/NWS climate-day OBSERVATIONS (actual recorded highs/lows,
   arriving in preliminary and final revisions) — not a forward-looking
   forecast. Every forecast number used in backtests today is synthetic,
   injected by test scaffolding. For each strategy, you MUST separate: (a)
   what it can run on using data that exists right now (venue quotes/book
   depth + historical NWS observations), from (b) what it would require
   Breezy to acquire first (e.g., a real forecast feed, a different venue's
   data, alternate weather models). Do not silently assume a forecast feed
   exists.

3. **PRICE HISTORY IS FORWARD-ONLY, NOT BACKFILLABLE.** There is no public
   historical trade tape for these markets. Once a market expires it returns
   a null price, retaining only its final settlement price. Do not design a
   strategy that requires reconstructing historical bid/ask time series for
   markets that have already closed. Settlement TRUTH, by contrast, is
   available historically and is venue-portable — both Polymarket.us and the
   eventual second venue (Kalshi) settle against the same NOAA/NWS
   observations, so historical settlement outcomes by station/date are usable
   for calibration and backtesting even though historical prices are not.

4. **NAUTILUS TRADER IS AN IMMUTABLE FOUNDATION.** It may only be extended
   through its own native extension points (custom `Strategy` subclasses,
   config objects, data subscriptions). Never propose modifying, patching,
   or reimplementing Nautilus internals. If a strategy needs a capability
   (an indicator, an order type, a portfolio query), first assume Nautilus
   already provides it natively and only propose new Breezy-side code where
   you can state concretely why Nautilus does not.

5. **RISK CAPS ARE MAX-PAYOUT DOLLARS, NOT MARKET VALUE.** `max_event_notional`
   and `max_location_notional` are computed as contracts x payout-per-contract
   (effectively face value at settlement), not the current cost to acquire
   the position. Size and reason about exposure in payout terms.

6. **MAKER ECONOMICS ARE UNEVALUABLE — DO NOT DEPEND ON THEM.** The fee model
   prices a maker (resting/posting) fill at the same coefficient as a taker
   fill, while the venue's real maker rate is documented as a REBATE (you'd
   be paid, not charged) — the model's sign is simply wrong for maker fills,
   and post-only orders are refused outright by the current implementation.
   No proposed strategy may rely on earning a maker rebate or on
   posting/resting limit orders as its source of edge. Assume every fill is
   a taker fill against the live ask.

7. **TWO OPERATOR-RESERVED CONTROLS HAVE NO ASSIGNED VALUE: maximum daily
   trading budget, and maximum notional per POSITION.** Do not invent or
   assume a number for either. Describe sizing as a function of these
   (currently-unset) caps rather than hardcoding a dollar figure.

8. **NO LOOK-AHEAD.** Settlement outcomes (the final NWS-observed
   temperature) are known with certainty after the fact, and it is easy to
   accidentally leak them into a signal computed "at decision time." For
   every strategy, state EXPLICITLY what information is known at the moment
   the decision is made (e.g., "yesterday's final NWS high for this station,
   published before today's market opens" is fine; "today's final NWS high"
   is look-ahead if the market being traded settles on that same value).

======================================================================
PART 3 — WHAT EACH OF THE THREE STRATEGIES MUST CONTAIN
======================================================================

For EACH of the three proposed strategies, produce all of the following.
The objective is increasing RISK-AWARE return on investment — novelty for
its own sake is not a goal.

1. **Name and one-sentence summary.**
2. **Edge hypothesis (falsifiable):** the specific, named inefficiency being
   harvested. Who is on the other side of this trade, and why do you believe
   they are structurally wrong or slow, rather than simply unlucky?
3. **Why this persists:** a reason the inefficiency isn't already arbitraged
   away (e.g., thin/illiquid market, no institutional weather-market
   participants, information asymmetry, behavioral bias, structural
   mispricing of a specific bucket shape).
4. **Loss conditions, stated up front:** the concrete market/weather
   conditions under which this strategy loses money — not hedged, not
   caveated, a real failure mode.
5. **Falsification test:** the cheapest experiment (using data described in
   constraint #2/#3 above as available-now vs. must-acquire) that would kill
   this idea, and the specific numeric threshold at which you would consider
   it dead. This is more important than the design itself — be concrete.
6. **Data dependencies**, split explicitly into two lists: "works with data
   Breezy has today" vs. "requires data Breezy would first have to acquire."
   If a dependency is in the second list, name what would need to be
   acquired and from where.
7. **Expected holding period**, and how the edge interacts with settlement
   timing (does it need to be entered early/late relative to settlement?
   Does the edge decay as settlement approaches, or strengthen?).
8. **Distinctiveness:** one paragraph proving this is NOT a
   re-parameterization of a "buy YES when my model probability exceeds the
   ask by more than a threshold, filtered by data freshness" strategy family
   — explain the mechanism difference plainly.
9. **Nautilus null-hypothesis check:** for any nontrivial computation the
   strategy needs (e.g., a rolling statistic, a portfolio-wide exposure
   query), state whether you assume Nautilus already provides it natively or
   whether it's new Breezy-side logic, and why.

======================================================================
PART 4 — FINAL RANKING
======================================================================

Rank the three strategies by expected risk-adjusted ROI, with your reasoning.
State which ONE you would build first, and why — weigh the falsification
test's cost/speed as well as the expected edge size.

======================================================================
PART 5 — OUTPUT FORMAT AND HONESTY REQUIREMENTS
======================================================================

- Output exactly three numbered strategy sections, each with the nine
  numbered fields from Part 3 in that order, followed by a "Ranking" section
  per Part 4.
- Where you are uncertain, say so explicitly — do not present speculation as
  fact. Use the literal phrase "this requires data Breezy does not have"
  wherever a strategy's data dependency falls in that bucket.
- Do not propose anything that violates any constraint in Part 2. If a
  promising idea is blocked by one of them, say so and either adapt it to be
  long-only/no-look-ahead/etc. or discard it — do not present a
  constraint-violating design and caveat it after the fact.
