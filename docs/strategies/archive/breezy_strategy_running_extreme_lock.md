> **ARCHIVED 2026-09-01 — IMPLEMENTED, not refuted.** Built as
> `src/breezy/strategy/running_extreme_lock/` (v1, commit d62566c). The code is
> authoritative; this doc is the original handoff spec and may have drifted.

# Breezy / Nautilus Strategy Handoff
## `running_extreme_lock`

Status: DESIGN ONLY — implement against the Breezy plug-in contract. Do not modify Nautilus internals. Do not add `__init__.py` or `pyproject.toml` registration.

Package path: `src/breezy/strategy/running_extreme_lock/`
Files: `config.py` · `decision.py` · `strategy.py`

Related (do not clone): `forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`

Build-first candidate among the three new strategies, **conditional on** the NWS client already emitting `is_final=False` rows for *today’s* `climate_day` while that market is still open.

---

### 1. Name and one-sentence summary

After a same-day, non-final climate-day record prints a running extreme that has already entered the open-ended tail (or, for an interior bucket, whose empirical remaining-excursion risk is below a threshold), buy YES on that one surviving bucket.

---

### 2. Edge hypothesis (falsifiable)

Named inefficiency: **high-water mispricing of path-dependent binaries**.

For a daily maximum, once the official running high `H` is already `>=` the lower bound of the open-ended “X or above” contract, that contract can only settle YES unless the observation is later revised down. Afternoon CLI (mandatory second issuance ~15:00–17:30 local, current climate day) and any later intra-day revision are public running extremes.

Hypothesis: after that print, the live ask on the already-cleared tail (or on a tightly haircut interior bucket) stays below `p_hold - cost` because forecast-shaped flow still prices off this morning’s point forecast or a weather-app current temp. The other side is structurally slow: the path constraint is in the observation, not in a forecast file.

Primary executable path: **open-ended upper tail already cleared**.
Secondary path (stricter thresholds): interior bucket containing `H`, haircut by empirical `P(H* stays in bucket | H in bucket, hour)`.

---

### 3. Why this persists

Forecast-shaped bots update when a model run lands, not when the official running max crosses a bucket floor. Retail anchors on “today’s high will be 87” after 87 is already in. Afternoon CLI is a specialist product. Exclusive-bucket risk prevents buying the whole remaining support, so Dutch-book pressure is blocked. Capacity is small, which is why a stale 30¢ ask can sit.

---

### 4. Loss conditions (unhedged)

1. Running extreme is revised **down** across the tail floor (sensor spike pulled; `correction_flag` / `revision_seq`).
2. Interior bucket treated as locked and the high later jumps one degree into the next bucket.
3. Civil-day max used instead of LST climate-day max (DST trap, especially KNYC / KMDW).
4. Remaining clock after the print still includes a climatologically common late peak and an interior bucket was bought anyway.
5. Ask already embeds the lock (`> ~0.97`) so after-cost edge is negative.

---

### 5. Falsification test

Prices are not required to kill the meteorology.

For each station-season, take every historical pair (non-final climate-day record at hour `h` with `tmax = H`, final same-day `tmax = H*`):

- Open-tail rule: on days where `H` already sat in the then-listed open tail, `p_hold = P(H* >= tail_floor | H >= tail_floor, h)`. **Dead if** `p_hold < 0.96`.
- Interior-bucket rule: `p_stay = P(H* <= bucket_upper | H in bucket, h)`. **Dead if** `p_stay < 0.80` at the afternoon issuance hour, **or** if `p_stay - median in-life ask - c < 0.03`.
- Do not use next-morning finals as if they were known at 16:00. That is look-ahead.

If the NWS client does not emit `is_final=False` records for today’s climate_day while the market is open, the afternoon path is not implementable on present feeds. See data split. Do not substitute a forecast.

---

### 6. Data dependencies

**Works with data Breezy has today**

- Live `OrderBookDepth10`
- Historical NWS finals for `p_hold` / `p_stay` tables
- Prior-day and revision history
- Bucket metadata via `read_weather_bucket_facts` / `WeatherBucketFacts.applies_to`

The afternoon executable path works today **only if** the NWS client already delivers non-final same-`climate_day` records intra-day. The schema fields `is_final` and `revision_seq` suggest this was intended. Verify before writing `strategy.py`.

**Requires data Breezy would first have to acquire**

If the client only posts a climate day after local midnight, **this requires data Breezy does not have**: same-day running official max. Acquire either:

1. Intra-day CLI issuances (NWS AFOS `CLI{ccc}`, IEM parsed CLI), or
2. Station METAR / LCD max-so-far **from the named settlement station only** (KNYC, KSFO, KMIA, KMDW, KLAX)

Do not use a city-average or weather-app high. Do not add a forecast feed.

---

### 7. Holding period and settlement timing

Enter late on the observation day (after the second CLI or a later revision). Hold through next-morning settlement — roughly 12–18 hours.

Edge is zero before a same-day official extreme exists. It strengthens as evening progresses without a new high and without a downward revision. Dawn entry is out of spec.

- Open tail already cleared: extra clock **helps** (further rise is harmless).
- Interior bucket: extra clock **hurts**.

---

### 8. Distinctiveness vs existing strategies and vs “model_p > ask”

The trigger is a path constraint on the official extreme, not a comparison of a forecast distribution to the ask. The strategy may emit **no signal at all** on a day when the running max never reaches the tail, regardless of how “mispriced” a forecast looks.

- `forecast_mispricing` is “my μ,σ vs bucket price.”
- `forecast_revision` reacts to model-run deltas.
- `calibration_mean_reversion` fades prices and is short-oriented in current form.

Decision shape: hard gate (`running H` already in the target set) → haircut only for revision / remaining-excursion → `LONG_YES` or `None`. Never `SHORT_YES`. `allow_short = False`.

---

### 9. Nautilus null-hypothesis check

| Need | Where it lives |
|---|---|
| Book + custom weather + clock | Nautilus native |
| Empirical remaining-excursion table | **new Breezy-side** — Nautilus EMA/SMA/etc. are price/bar stats and do not know climate-day extremes |
| Max-so-far vs bucket bounds | **new Breezy-side** pure function in `decision.py` |
| Exposure clip | existing `RiskManager` (payout dollars, exclusive-bucket) |
| Nautilus internals | **do not touch** |

---

### Plug-in contract (implement exactly)

**Config** — `frozen` subclass of `nautilus_trader.trading.config.StrategyConfig`.

```
allow_short: bool = False
open_tail_only: bool = True          # recommended first ship
min_p_hold: float = 0.96             # open tail
min_p_stay: float = 0.80             # interior; ignored if open_tail_only
min_hours_remaining_interior: float  # refuse interior if too much clock left
require_same_climate_day: bool = True
require_not_final_ok: bool = True    # preliminaries are the point
```

Do not invent dollar figures for maximum daily trading budget or maximum notional per position. Size as a function of those when set, plus existing payout-dollar caps.

**decision.py** — PURE.

Algorithm:

1. Ignore the record unless `WeatherBucketFacts.applies_to(station, climate_day)`.
2. Ignore if climate_day is not the instrument’s settling day.
3. Read running extreme (`tmax_f` for high markets, `tmin_f` for low markets). None → `None`.
4. Classify the instrument:
   - Open-ended upper tail (high markets): running `H >=` tail lower bound → candidate. `model_p = p_hold(station, season, hour)`.
   - Open-ended lower tail (low markets): only if running `tmin` is already `<=` tail upper bound **and** remaining downward risk is tabled. Default off until tmin tables exist.
   - Interior: only if `open_tail_only` is False and running value is inside the bucket. `model_p = p_stay(...)`.
5. If running value is already **above** an interior bucket’s upper bound, that bucket is dead. Return `None` (do not short it).
6. `edge = model_p - ask_p - cost`. If below min edge, `None`.
7. Emit `LONG_YES` only.

Look-ahead: use only records with `timestamp <= now`. Do not read the final for the same climate_day before it has arrived.

**strategy.py**

- Subscribe `OrderBookDepth10` per instrument and client-scoped NWS data.
- On every NWS record: filter station/day; update running extreme state; re-evaluate only matching instruments.
- On book depth: re-evaluate that instrument against stored running extreme.
- Then `RiskManager.evaluate_order`. Then Nautilus submit.
- Taker against live ask only. No post-only. No maker rebate.
- Exclusive-bucket: this strategy wants **one** long YES per event. Do not try to buy two surviving buckets.

**Risk gate:** same 10-check list as every Breezy strategy. `forecast_age_hours` — this strategy has no forecast. Do not fake a forecast. If the stale-forecast check requires a forecast age, treat the **observation record age** as the freshness input if and only if that is what the existing gate already means operationally; otherwise flag an implementation blocker.

Event/location caps are `contract_size × contracts` (max-payout dollars), grouped by `event_key = "{settlement_station}:{climate_day}"` and `location_id = settlement_station`.

---

### Look-ahead rule (non-negotiable)

Known at decision time: live book; same-day *already-issued* preliminaries; historical finals from **previous** climate days for the excursion tables.

Not usable: today’s final before its timestamp; any synthetic forecast; reconstructed tapes of expired markets; METAR from a non-settlement station.

---

### Sizing

Conviction is higher for open-tail-already-cleared than for interior `p_stay`. Quantity is the residual room under payout-dollar caps and the two unset operator controls (daily budget; max notional per position). Do not hardcode dollars.

---

### Implementation notes for the Nautilus / Breezy agent

1. First action: grep the NWS client / fixtures for `is_final=False` records whose `climate_day` equals a still-open market’s settling day. If none exist, **stop and report**. Do not invent METAR inside this strategy.
2. Copy folder layout and risk-call pattern from an existing long-capable strategy. Two of the three current strategies emit only `SHORT_YES` and are refused by `allow_short=False` — do not copy their intent side.
3. Ship `open_tail_only=True` first. Interior buckets are a second increment after `p_stay` tables exist.
4. Registration: new files, imported by direct name. No `pyproject.toml` / `__init__.py` edits.
5. Backtest through existing `run_backtest` harness only.
