I'll start from the binding lessons and the three lock-strategy refutations, then design a calibration-edge strategy only in the region that still has an offer. No files will be changed.Lessons L-7 and L-9 are in view. Next I’ll read the H4 refutation, the climatology evidence, and the strategy that just died.The lock family is closed. I’ll pull forecast-probe, fee, and microstructure evidence next so the calibration-edge design is grounded in measured numbers, not a fourth lock.Fee formula and venue microstructure are in. Next I’ll pull forecast-probe, cost, and existing-strategy docs so the model and kill criteria sit on measured numbers.The late-day 0.01 dump is not the trade. The only live cell is a **pre-event cheap rung the forecast has moved toward and the sticky 6-rung ladder has not**. I am not designing a fourth lock, and I am not claiming this family works — I am specifying the one mechanism that could, and the cheapest measurement that kills it.# H5 — Sticky-ladder cheap rung

**Status:** design only. No files changed. No backtest, no simulated trade, no P&L.

**One-line:** A long-only taker buys YES on a still-open rung offered at **≤ 0.03** when a CLI-calibrated table, conditioned on a point-in-time Open-Meteo previous-run, says that rung is a several-percent event, not a 1% event. Hold to settlement.

This is not a retune of `forecast_mispricing`. That strategy requires a two-sided quote (`decision.py:86-87`), `min_entry_edge = 0.06`, a unimodal Gaussian around a scalar `expected_high_f`, and an exit that needs a bid. On this venue that is the wrong object.

---

## 0. Two populations of 0.01 asks — do not mix them

The inverted-liquidity table in the brief is real, and it is **the post-determination book**.

H4 on climate day 2026-08-31 (`docs/evidence/h4_preliminary_economic_read_2026-09-01.md` §4): every non-winning rung offered on ~100% of snapshots at **0.01–0.03**; the winner uniquely unoffered (MDW/MIA/NYC/SFO) or offered at **0.99** (LAX, 7/63 snapshots, all before the 18:00 LST trigger). Independent re-read of MDW’s winner: **0 asks / 876 rows over 13.3 h**. That is L-7/L-9: the trade has no seller.

Those 0.01 rungs are the ones the day has **already missed**. True P is residual basis / late-rise, not “a 1% event.” Buying them is buying a lottery that has already lost, paying the 0.01 tick floor as a tax. H1/H2 are the same object in costume: listed tails 4–8 F from the printed high, trigger 0/4, asks 0.01 correctly pricing a non-event (`docs/evidence/first_in_window_capture_2026-09-01.md`, `docs/evidence/h2_lower_tail_rejected_2026-09-01.md`).

**H5 is forbidden from that population.** If the only 0.01 size you can lift is the post-peak dump, this family is dead and I would say so. The live cell is earlier.

The **pre-event** book is a different object, thinly measured:

| when | what we have |
|---|---|
| Discovery 2026-08-30, MDW 08-31 ladder | best-**bids** 0.30+0.26+0.09+0.03+0.01+0.29 ≈ 0.98 — a spread-out partition, not 0.01/0.99 (`polymarket-us-integration` skill discovery log) |
| Capture 2026-09-01 00:41–00:59Z, **next-day** (09-01) upper tails | MDW 0.20–0.21 (n=928), SFO 0.09 (n=153), LAX/MIA/NYC 0.01–0.02 (`first_in_window_capture`) |

So D+1 tails are sometimes a real probability (0.09–0.21) and sometimes the 0.01 bin. H5 only fires on the second case, and only when the table says that bin is wrong.

Open universe is **5 cities × 2 climate days × 6 rungs = 60** (`skill` discovery 2026-08-30). D+1 is listed and trading during D0. That overlap is the window.

---

## 1. Where the market is plausibly miscalibrated — the mechanism

Not “the market is dumb.” Three stacked, named mechanisms. Only the first is required; the other two are station-specific fatteners.

### M1 — Sticky 6-rung ladder vs moving forecast (primary)

The venue lists a **fixed** 12 F window: one `lt<N>f`, four inclusive 2 F interiors, one `gte<N>f`. That grid is placed when the city-day is listed (~24–48 h out) and **does not move**. Forecasts do.

Open-Meteo previous-runs already serve hourly `temperature_2m_previous_day1..7` on `previous-runs-api.open-meteo.com/v1/forecast`, unkeyed, valid-time anchored, archive to 2019 (`docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z/PROBE_REPORT.md`). Default Breezy error model at 24 h is σ = 2.8 F, at 48 h σ = 3.7 F (`probability.py:409-420`). A 3–6 F overnight revision is ordinary NWP. A 2 F rung under a 3 F revision is a different contract.

The MM **can** reprice (MDW 09-01 tail at 0.21 proves it). The harvestable error is if they reprice the favorite toward 0.99 / empty-ask and **leave the newly-likely cheap rungs in the 0.01 dump**, rather than lifting those asks to 0.05–0.15. H4’s late book is consistent with “everything that is not the winner is 0.01.” If that dumping rule is applied **before** determination, M1 is live.

This survives because it is a **product design** fact (sticky 6-rung grid, 0.01 tick, exhaustive partition), not a speed race. L-7’s amendment still holds: once the outcome is physically determined, the offer on the winner is gone. H5 never waits for that clock.

### M2 — Value bimodality at LAX / SFO (not T* bimodality)

PMR PR-2: `T*` is **unimodal** at LAX and SFO in all four seasons (`pmr_climatology_2026-09-01.md` §4). That killed a clock-rule carve-out. It says nothing about the **value** of `tmax`. Marine-layer vs burn-off/offshore is a two-mode temperature, one afternoon peak. A 12 F ladder centered on a point forecast covers one mode; the other mode sits in an open tail.

A Gaussian around `expected_high_f` (what `WeatherProbabilityEngine` is) puts mass in the trough that does not happen and starves the tail that does. If the MM is the same shape — NWS/ECMWF deterministic high, Gaussian error — both sides miscalibrate the same way, and there is no edge. If the MM is a point-forecast plus a 0.01 dump of the far rung, the fat tail is underpriced. **Unmeasured.** Gate K2 below.

### M3 — Convective cap at MDW / MIA; NYC instrument basis

MDW DJF: `P(T* > 17:00 LST)` = 11.8% ASOS / 22.8% CLI (PR-1 false). Overnight max on a warm advection night, plus summer convection that **caps** the high below the morning forecast. The mass that a deterministic high puts on the upper interiors belongs on the lower interiors / lower tail.

NYC METAR↔CLI basis: n=1736, mean **+0.655 F**, median **+1**, `P(|Δ|≥1)=56.0%`, `P(|Δ|≥2)=8.5%` (`pmr` §2). Any model that treats an observation-derived max as the settlement integer is a 1 F miss on a 2 F rung — the H3/H4 kill. The MM settling on CLI should already know this; an OM-grid or METAR-naive crowd may not. H5’s table is fit to **CLI integer**, so this is absorbed as bias, not left as a rounding patch.

### What would make M1 die immediately

If, on the D+1 book, every rung the latest previous-run puts ≥3% on is already asked at ≥0.05, the MM is looking at the same NWP and the sticky-ladder gap is closed. That is kill criterion K4. It does not need a backtest.

---

## 2. Entry

**Instrument.** Any of the six rungs of a listed city-day, including interiors. Not tail-only (`lagged_anomaly_tail` already occupies that narrower claim and forbids forecasts).

**Price.** Taker lift of the live ask. Hard ceiling **0.03**. Prefer 0.01. Never 0.04+ — that is not the liquid cheap region, and it is not this strategy.

**Clock, relative to the climate day** (local STANDARD midnight = Breezy `_climate_day_end_ns`):

| phase | allowed? |
|---|---|
| D+1 listed, climate day not started | **yes** — primary window |
| D0 before local diurnal peak, rung still open (see below) | **yes** — secondary, tighter table |
| D0 after peak / H4 trigger hours | **no** — that is the lock book |
| After any CLI preliminary or final | **no** — L-7, public information, no offer on what you want, dump on what you don’t |

**Still-open (physical filter, ASOS `R(t)` plus NYC-sized basis):**

A rung is **closed** and untradable for H5 when it cannot settle given `R(t)` except via **negative** basis:

- Interior `[A, A+1]` or lower tail `lt N`: closed once `R(t) ≥ A+2` (or `≥ N+1`), i.e. the running max is at least 2 F above the rung’s ceiling. The extra 1 F is the NYC-median basis, applied at every station so the rule is not silently METAR-as-CLI. Tighten per-station only after the table is fit.
- Upper tail `gte N`: never closed by `R(t)` going **up**. Closed only when the climate day has ended **and** `R(t) < N−1` (cannot reach the floor even with +1 basis).

This is the H1/H2 lesson as a gate: do not buy a 0.01 on a rung the day has already missed.

**Forecast state.** A previous-run snapshot whose `ts_init` (availability) is ≤ decision time. Stale if older than 8 h (`stale_forecast_hours` already in `RiskLimits`). No snapshot → no trade (`ForecastSource.snapshot → None` already means skip; never fabricate from CLI).

**Numeric entry.** Let `a` = depth-aware ask VWAP from native `OrderBook.simulate_fills` (L-1c in `docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`; do not hand-roll a walker). Venue fee `θ = 0.06` on 60/60 weather markets:

```
cost(a) = a + θ · a · (1 − a)
```

At the three legal asks (derived, not traded):

| a | fee | cost = break-even P |
|---:|---:|---:|
| 0.01 | 0.000594 | **0.010594** |
| 0.02 | 0.001176 | **0.021176** |
| 0.03 | 0.001746 | **0.031746** |

`transaction_cost_prob = 0.015` is the **p=0.50 maximum** of that fee curve (BL-19). It is the wrong constant here by 25×. Use the function.

Entry iff:

```
Wilson_95_LOWER( table cell ) − cost(a) ≥ 0.01
```

The 0.01 is one tick of adverse-selection haircut, not a mid-prob `min_entry_edge`. Equivalently: at 0.01 need Wilson-lower **≥ 2.06%**; at 0.02 **≥ 3.12%**; at 0.03 **≥ 4.17%**.

If several rungs on the same city-day pass: take **one**, the max of `Wilson_lower − cost(a)`. `allow_overlapping_exclusive_yes` stays **False** (`risk.py:138`). Two rungs of one city-day are one bet.

`quote_tradable` must accept a missing bid (already true in `RiskManager.quote_tradable` for one-sided books). `forecast_mispricing`’s `if bid_p is None or ask_p is None: return None` must not be reused.

`allow_short` stays False. Never buy NO, never sell what we do not hold.

Do not assign values to max daily budget or max per position.

---

## 3. The model — a table that predicts the CLI integer

Not `WeatherProbabilityEngine.bucket_probability(expected_high_f, σ)`. That is a unimodal Gaussian on a METAR-ish scalar. H4 already recorded that a flat threshold is the wrong shape; a Gaussian around a point forecast is the same mistake in forecast space (especially M2).

**Target.** `Y = CLI final tmax_f` (integer), `is_final=True`, `is_superseded=False`. Never ASOS daily max, never OM hourly max rounded.

**Inputs, all known at decision time:**

| symbol | source | notes |
|---|---|---|
| `OM_max` | max of hourly `temperature_2m_previous_dayN` over the climate-day hours in **local standard**, converted °C→°F | daily OM variables 400 (`PROBE_REPORT` findings); must derive from hourly |
| `OM_spread` | max−min of `{best_match, ecmwf_ifs025, gfs_seamless, icon_seamless}` same valid-time window | four models already 200 on the probe |
| `d` | signed distance of the rung from `OM_max`, in the ladder’s 2 F grammar | `d = 0` means the interior containing `OM_max` |
| `station, season` | facts | DJF carved in separately at MDW (PR-1) |
| `phase` | `{pre_event, d0_open}` | `R(t)` only exists in D0 |
| `h` | `upper_f − R(t)` when D0, else `NA` | headroom in ASOS units; table must still emit CLI probabilities |
| LAX/SFO only: `regime` | `OM_max` vs that station-season’s CLI median, binary `cool/hot` | proxy for marine vs offshore; replace later if a better OM field (dewpoint/wind) is probed |

**Cell.** Frequency table:

```
P(Y ∈ rung | station, season, d, OM_spread_bin, phase, regime)
```

Wilson-95% **lower** bound is `model_p`. Empty cell → no trade (`n/a`, never 0 — same doctrine as PMR). `min_samples` = 40, matching `ForecastErrorModel.min_samples_for_local`. Coarser fallbacks: drop `regime`, then `OM_spread_bin`, then `season`. Never fall back to a scalar σ.

**Basis.** Fit `Y − round(OM_max)` empirically per `(station, month, horizon_bin)`. That single residual **is** the two-hop (grid→ASOS→CLI). Do not apply the PMR METAR↔CLI table on top of it — that would double-count ASOS. Do not use `continuity_correction_f = 0.5` as a substitute for this fit.

**Lookahead.** `fit` on records with `target_date < train_end_exclusive` (`calibration.py` already raises). Probe captures in `docs/evidence/open_meteo_previous_runs_probe_*` are **EVIDENCE ONLY — NEVER INGEST** (both probe reports). A production `LiveDataClient` must stamp `ts_init` = retrieval time. Backdating a previous-run under a plausible timestamp is lookahead.

**Archive hole.** `archive_reaches_2024_01 = REFUTED` (`open_meteo_coverage_bisect_probe_2026-08-31T011135Z`). 2022–2023 contiguous; 2024-01-01 all-null on every model tested. Training is ~2019–2023 plus whatever 2025–2026 the next coverage probe clears. Do not claim “five years of forecasts” until 2025 is measured.

**Nautilus seam (L-1).**

| need | verdict |
|---|---|
| Strategy | **NATIVE** — subclass `nautilus_trader.trading.strategy.Strategy` |
| Forecast ingest | **GENUINELY ABSENT** in Breezy — `forecast_source.py:5-8`. Smallest extension: `LiveDataClient` polling previous-runs (fetching → client, not Actor) + hand-written `Data` + one `register_arrow`. Not `@customdataclass` (hourly series, nulls, `date`). |
| Catalog | **NATIVE** `ParquetDataCatalog`. Trap 21: custom type without `instrument_id` writes flat — one catalog root per station, or put `instrument_id` on the type. Trap 1: corrections are new `ts_init`, never same-range rewrite. |
| Depth VWAP | **NATIVE** `OrderBook.simulate_fills` |
| Fill-time fee | Breezy `PolymarketUSFeeModel`. Do **not** import `nautilus_trader.adapters.polymarket` (`.com`, import-linter, fail-open `taker_fee`). Gate-time `cost(a)` is a pure helper; `FeeModel.get_commission` is post-fill only. |
| Backtest of H5 | **Not this task.** A forecast archive is a **calibration dataset**. Prices are forward-only (`PROGRESS.md` standing verdict; both OM probe reports). Nautilus owns any later backtest once a forward tape exists. |

`ForecastSnapshot.expected_high_f` is too thin. H5 needs hourly previous-runs plus spread. Do not overload the existing snapshot to pretend a point forecast is a table.

---

## 4. Exit / holding

**Hold to settlement.** Necessarily.

The bid side is structurally empty on the cheap rungs (skill: one-sided books are normal OTM; brief: median top-of-book bid ~0.3 contracts). There is no exit market a taker can sell into without crossing a 0.01 bid that is not there.

`flatten_on_observation` after a **final** CLI is optional and only if someone is bidding 0.99 on a position already worth 1. That is a bonus, not a rule. Do not flatten on a preliminary (G-01: MDW/NYC/SFO interior revision rates fail).

No mid-life “edge decay” exit. That path in `forecast_mispricing` needs a bid.

---

## 5. Sizing and capacity

At 0.01–0.03 the book is not the bind. Median offered size on non-winning rungs is **35,991** (max 767,198) per the brief; `min_liquidity_contracts = 25` is noise.

What binds:

1. **One reading settles all six rungs.** Exclusive-YES stays on. Size is per **city-day**, not per rung. Buying three 0.01 interiors on MDW 09-01 is one 3¢-per-contract parlay on a single `tmax_f`, not three bets.
2. **Adverse selection.** The 0.01 size that remains after a forecast revision toward that rung is the size the informed MM is willing to sell. Phantom depth that evaporates on lift is the capacity question, not the 36k resting.
3. **Cross-city correlation.** A synoptic pattern hits NYC+MDW the same day; LAX+SFO share marine regime. `max_location_notional` is per station; it does not cap a five-city frontal day. Existing `max_simultaneous_positions = 12` and `max_event_notional = 1_000` (payout dollars, L-2 — do not silently swap for MTM `net_exposure`) are the engineering caps. Operator max-per-position / max-daily-budget stay unset.
4. **Variance, not edge.** 100:1 payoff. A 3% event at 0.01 has positive fee-schedule EV **if** 3% is true; sample-path ruin on 50 losing tickets is the operational limit. That is why Wilson-lower, not a point P.

Engineering clip (not an operator control): size so `qty × $1 ≤ max_event_notional` on the **payout** unit already in `risk.py`. Depth-walk the ask until VWAP would breach the 0.03 ceiling or `simulate_fills` exhausts; take the min of that and the event cap.

Fee rounding: `θ C p (1−p)` banker's-rounded to $0.01. At p=0.01, C=1 the fee is $0.000594 → $0.00. Do not “discover” a free-fee edge; size at intended clip and compute fee at that C.

---

## 6. Pre-registered kill criteria — economic gate first

The programme has twice terminated at “settlement PASS, economics unknown” (`FEEDBACK_FOR_GROK` §1; H4 “Do not build before that gate reports”). Forecast ingestion is required to **trade** H5 (L-9). It is **not** required to kill H5. Kill first.

Each criterion is falsifiable and names the measurement. None is a Nautilus backtest.

**K0 — tape integrity (L-8).** `breezy-quote-tape-preflight` INTACT on every file in the window before any count below is interpreted. A 0-row is not a quiet market.

**K1 — ECONOMIC, cheapest, no model, no forecast. THE FAMILY KILL.**

On captured **D+1** (and D0-morning) depth, define a snapshot-rung as **cheap-open** iff `ask ≤ 0.03` and the still-open rule in §2 holds.

Let `π = P(that rung’s city-day settles YES | cheap-open)`, one row per (station, climate_day, rung) using the **first** cheap-open snapshot that day (not every 5 s tick).

- **Dead if** Wilson-95% **upper** bound of `π ≤ 0.010594` (break-even at 0.01 after fees). Then even a perfect model cannot concentrate enough: the cheap-open set as a whole does not pay, and the MM is dumping correctly.
- **Not confirmed if** `π` is high — that can be “the favorite was also 0.03 that morning.” Stratify by whether the rung contains the then-current OM max (`d=0` vs `|d|≥2`). The interesting cell is `|d|≥2` and still cheap.

Denominator needed: ~100 station-days of D+1 books (20 calendar days × 5 cities) for a 1% rate to be distinguishable from 3%. Today we have **n ≈ 1** climate day of D+1 prices and no 09-01 settlement in the H4 document. This is Gate 0. **Do not ingest Open-Meteo, do not write a strategy class, until K1 reports.**

**K2 — M2 unmeasured. Value-modality, not T*.** Histogram of CLI `tmax_f` at LAX and SFO by season (n≈450/season already on disk). Dead-as-fattening-mechanism if unimodal with IQR ≲ 6 F: a 12 F ladder covers the mass and tails are not fat. Does not kill M1.

**K3 — table skill in the cheap region only.** Leave-one-year-out on 2019–2023 previous-runs vs CLI. Compare log-loss of the table vs (a) unconditional monthly climatology of the listed-shape tails, (b) Gaussian `WeatherProbabilityEngine` with fitted bias/σ. **Dead if** the table does not beat (a) by ≥ 0.01 mean log-loss **on the subset of rungs that would have been cheap-open**, or if buy-cell realized frequency is within 2 pp of the flat monthly rate. Do not score the favorite rung — we cannot buy it.

**K4 — M1 mechanism.** On D+1, when `|OM_max − rung_mid|` shrinks by ≥ 3 F across two previous-runs and the rung is still open: does the ask **leave** {0.01, 0.02, 0.03} within 60 min of the new run’s `ts_init`? **Dead if** ≥ 80% of such events already have `ask > 0.03` at the first post-revision snapshot. The MM saw the same NWP.

**K5 — phantom size.** Of cheap-open asks with displayed size ≥ 25, what fraction still show ≥ 25 on the next snapshot ~5–15 s later (capture cadence)? **Dead if** persistence < 50%: the 36k is not liftable.

**K6 — settlement-side, last, and only on cells K1–K5 left alive.** In buy cells, Wilson-lower on realized hit rate vs `cost(a)+0.01`. This is the H4 mistake if run first; it is a confirmation if run last.

Ordering: **K0 → K1 → (K2 ∥ K4 ∥ K5) → K3 → K6.** K1 failing ends the family. Forecast ingestion starts only if K1 survives.

---

## 7. Steelman: this family is dead too

The strongest opposite view:

The 0.01 bin is the MM’s **inventory dump** for every rung they do not want to be long. Tick size is 0.01, so a 0.3% event and a 1.5% event print the same. The size that remains at 0.01 after a forecast move is the size an informed seller is happy to give you (winner’s curse). Public NWP is not private; Open-Meteo is a wrapper around GFS/ECMWF/ICON, which is what the other side already runs. L-7 generalized: you cannot buy what the other side also knows is likely, and you **can** buy what they know is unlikely — that is why the offer is there. The late-day tape already showed this with n=4 station-days and 0.00% asks on winners; the early tape will show the same partition, just with the probability mass not yet collapsed to one rung. H1’s 4–8 F listed tails at 0.01 are not a misprice, they are a 2% Gaussian tail (σ≈2.8 F at 24 h, `1−Φ(6/2.8)≈1.6%`) sitting on a 1% tick — **fair to slightly expensive after fees**, not 100:1 juice. `p_floor=0.01` in the existing engine is an accidental confession: the model cannot even *state* a sub-tick edge.

If that view is right, K1’s `π` lands at or below 1.06% and the family dies in one measurement.

**Single cheapest measurement that settles it:** K1. First cheap-open snapshot per (station, day, rung) on the D+1 book, scored against the eventual CLI final. No forecast client, no strategy, no Nautilus run, no fee model beyond the closed-form break-even. Preflight the tape (L-8). n=100 station-days of capture already in motion under the H4 supervisor is enough to reject 3% vs 1%.

If K1 kills it, that saves the forecast-ingestion build **for this family**. Forecast ingestion can still be a programme capability (L-9); it should not be justified by H5.

---

## Verdict

I do **not** believe the honest answer is “no calibration strategy can work on this venue.” I do believe the honest answer is:

- Every lock is dead (L-9). Do not build H6-as-lock.
- The **late** 0.01 dump is dead. Do not harvest H4’s 36k.
- The **only** remaining cell is pre-event cheap-open rungs, priced off a sticky ladder, scored by a CLI-integer table. That cell is **unmeasured**. Today’s tape is almost entirely the dead cell.
- Existing `forecast_mispricing` / `forecast_revision` / `calibration_mean_reversion` cannot be pointed at this cell without changing the quote contract, the cost function, the probability object, and the hold rule. That is a new strategy, not a knob.
- **Do not implement H5 until K1 reports.** If K1’s Wilson-upper on `π` is ≤ 1.06%, I will call the family dead and that will have been the correct 60-day save.
