> **STATUS 2026-09-07 — DESIGN v2, PEER-REVIEWED, NOT REGISTERED, NOT IMPLEMENTED.**
> Produced by the strategy designer (Grok) from a coordinator-verified evidence sheet
> (four read-only investigations of this tree at `ccf9161`), then revised against three
> independent adversarial reviews (trading-bot-architect, prediction-market-reviewer,
> Codex second-model) — all three returned ACCEPT-WITH-CHANGES on v1; every change is
> logged in §14; a convergence pass then corrected three items (§14, V1–V3). Gate record: `docs/evidence/ladder_ev_peer_review_2026-09-07.md`.
> §12 C12 pre-check: `docs/evidence/ladder_ev_afternoon_coverage_census_2026-09-07.md` —
> train 7/15 covered station-days on 2026-09-07 ⇒ structural-dead branch UNREACHABLE (INSUFFICIENT DATA).
> Binding: `allow_short=False` permanent; BUY-YES / IOC / LIMIT / qty=1 only; DEGRADED
> mode only (no forecast ingest exists); SHADOW/REPLAY ONLY while `current_rung_hold`
> v2 is the registered live family (§2.4). Evidence-sheet item IDs (A1…D9) cited below
> refer to the sheet reproduced in the evidence record. Nothing here is a trial, a
> verdict, or an enablement.

# LADDER_EV — whole-ladder opportunity scanner (design v2)

Family id: `LADDER_EV`. **Registers as DEGRADED-only.** FULL mode is gated on a forecast `Data` type + `load_forecast_asof(as_of_ns)` that does not exist (C5/C9). PREREG = §9.1. All unmeasured quantities are tagged **ASSUMED** / **UNMEASURED**.

---

## 1. Summary

**Falsifiable claim:** among listed, *undetermined* Polymarket.us weather rungs in the DEGRADED ENTRY universe (§2), the information-conditioned conservative probability \(P^L(r\mid\mathcal{I}_t)\) exceeds the unified cash cost \(C\) (§5) by a horizon-aware margin often enough that filled \(q=1\) IOC BUY-YES takes have \(\mathbb{E}[\mathbf{1}_{\text{held}}-\mathrm{BE}]>0\).

Mechanism: one `Strategy` scans listed climate instruments on a timer, reads books from `cache.order_book` (D1), computes \(P\) from running-max information, prices intended size off a fail-closed depth walk, ranks by **absolute expected profit per contract**, and takes at most one BUY-YES per city-day that clears `margin(h)`. Not a fourth lock (L-9 / B1). **Refuses determined cells by rule** (§5.2). Buys only inside `(0.05, 0.95)` against conservative \(P\), the same economic object as M_B (A1–A3) scored across the ladder with executable depth, not a first-quote latch.

While CRH is live on the same account, this family is **SHADOW/REPLAY ONLY** (§2.4).

---

## 2. Universe & discovery

**Observed/scored universe (B3):** 5 cities `{LAX, MDW, MIA, NYC, SFO}` × daily HIGH × 2 climate days × 6 rungs (`lt`, four 2 °F closed interiors, `gte`) = **60 markets**. ~9% of station-days never list. Tick 0.01 on 3743/3743; `minimumTradeQty` 0.01 since 2026-06-14 (live decimal fill **UNRESOLVED** — PREREG stays integer `q=1`).

**DEGRADED ENTRY universe (C6, binding for takes):** 4 stations (NYC out, L-13 / B1), climate day **D only**, `hour_lst ∈ [12:00, 17:00)` LST (the PREREG afternoon window that also defines structural-dead, B6), with a running max **present and not spanning** the ladder. D+1 rows are **audit-only** until FULL (no \(M_t\) ⇒ climatology comparator, L-21). NYC and D+1 remain in the scored/audit table.

**Listing clock (B3):** created/startDate D−1 ≈ 09:45Z; `gameStartTime` D 05:00Z; `endDate` D+1 05:00Z. Settlement = NWS CLI next day 08:00 ET (METAR conflict → 11:00 ET; 7-day fallback). Corrections 0.14% in the archive.

**Scan cadence:** native `clock.set_timer` (D6), interval `scan_interval_s=15` **ASSUMED**. Not CRH’s first-QuoteTick latch (A1). Ranking is synchronized across books; WS depth is consumed from `cache.order_book` (D1) at fire time. Entire `on_scan` / `on_rediscover` bodies catch/log/latch (L-16, §10).

**Discovery — Strategy never issues venue GETs (C1).** Listing is owned by the DataClient: `PolymarketUSInstrumentProvider.load_all_async` / `_discover_markets` (`src/breezy/adapters/polymarket_us/provider.py:323-496`) and `PolymarketUSDataClient._update_instruments` (`data.py:1048-1096`) already reload forever on `_next_reload_delay_secs` under `QUOTA_KEY_DISCOVERY`. Floor 60 s, ceiling `DISCOVERY_RELOAD_CEILING_SECS = 21600` (`data.py:248-264`).

LADDER_EV:

1. Seeds from `ParquetDataCatalog.instruments()` **without** CRH’s `climate_day == today` filter (`composition.py:116-149`) — keep both listed climate days.
2. On `rediscover` timer (`rediscover_interval_s=300` **ASSUMED**): `self.cache.instruments(venue=POLYMARKET_US)` and **diff** against the subscribed set. Subscribe new HIGH ids for D and D+1 via `self.subscribe_order_book_depth`; unsubscribe expired. Native Strategy already subscribes N books (D1).
3. One Strategy instance for the scored 60-id set (ranking is cross-station). Per-station CRH composition is not reused.

The GL-8 fix (reload clamp 21600 s; late-listed rungs reaching a frozen compose set) is a **DataClient-side change on a separate track**. LADDER_EV diffs cache rather than freezing compose, but cannot see an instrument the DataClient has not loaded. **This family’s currency is bounded by that reload cadence.**

### 2.4 Coexistence with the live family (C2)

CRH (M_B v2) is the registered live family, composed as per-station strategies (`composition.py:197-208`; `app/trade.py:180-193`). **CRH does not use `SharedExposureView` at all** — `SharedExposureMixin` (`weather_common/shared_exposure.py:48`) is mixed into the forecast and lock families only, and CRH's one-position-per-station-day guarantee comes from its own trial-day latch (`current_rung_hold/trial_day_latch.py`, `strategy.py:386-387,467-474`), not from `exclusive_conflict`. `exclusive_conflict` only sees contracts registered in the **same** view (`weather_common/risk.py:393-526`), so today NO view sees CRH's positions. The AMBIGUOUS submit-intent latch is **account-wide** (B4, GL-4).

**Rule:** LADDER_EV runs **SHADOW/REPLAY ONLY** while another family is live on the same account. A live LADDER_EV requires (a) retrofitting the LIVE CRH strategy with `SharedExposureMixin` and composing both families onto **ONE** `SharedExposureView` (so `max_per_city_day=1` holds across families) — this is a change to deployed trading code, **outside §13's scope**, and would itself be a CRH family change under B6 — **or** (b) CRH retired, **and** (c) operator-only enablement. Until one of those happens the only honest coexistence is shadow/replay. An AMBIGUOUS from either family burns the other’s day. Concurrent live families are a **PREREG contamination risk**: one family’s zero-fill day is not the other’s structural-dead evidence.

---

## 3. Fair-probability model \(P(r\mid\mathcal{I}_t)\)

Ladder \(r\) is a closed bucket (`WeatherBucketFacts`). Partition identity: \(\sum_r P(r)=1\) after clipping. The `lt` rung is **in the partition** (audit + renormalisation) and **refused for ENTRY** (X11).

### 3.1 Inputs (availability-stamped)

| Input | ts_init | DEGRADED | FULL (not this family) |
|---|---|---|---|
| Running max \(M_t=[M^L,M^U]\) from `StationObservation` / `RunningMax` (`running_extreme.py:153-202`) | `received_at` (C4, C7) | required for ENTRY | truncator |
| CLI-archive density table (NEW, §11) | issuance (C3) | \(P\) | prior / fallback |
| Hours to local-standard end of climate day, \(h\) | clock | TTR / margin | TTR / margin |
| Forecast point + issuance lead | `available_at_ns` | **unavailable** | \(P\) |
| CLI prelim/final | `retrieved_at_ns` (C2) | determination / halt | same |

Obs lag measured (C4): IEM 19–43 min (MDW); NWS API ~21 min; NYC hourly ~45 min. Stale gate: `stale_observation_minutes=50` (CRH, `config.py:85`). NYC **excluded from ENTRY** (B1 / L-13). D+1 before a running max exists is scored for audit and **refused for entry** (L-21).

### 3.2 DEGRADED functional form (what this family registers)

CRH’s `P_HOLD_LOWER` is a **selector** on the current rung, not a density (A2, L-21; `archive_table.py:35`). LADDER_EV needs \(P(r\mid\text{station},\text{season},\text{hour_lst},m)\) for **every** listed rung.

Let \(m=\mathrm{round}(M^L)\) when `RunningMax.spans(ladder)` is false; else refuse (`observation_ambiguous`, `decision.py:276-277`).

**Density table (C16).** Built from IEM AFOS CLI labels (C3: 9,185 station-days, 2020-12-19..2026-08-24) with the **same** station / season / hour_lst / width / \(m\) keying as CRH (`decision.py:235-246`; width 0 = interior_2F, 1 = open_upper `gte`, 2 = open_lower `lt`) but as a **full 6-rung conditional distribution**, frozen with a corpus SHA at registration (`archive_table_pin`). CRH’s table has **no** width_code 2 keys (`archive_table.py:35` header / `_is_legal_cell`).

\[
\hat p(r\mid k)=\frac{k_r}{n_k},\quad
P^L(r\mid k)=\text{Wilson-95% lower}(k_r,n_k),\quad
\sum_r\hat p(r\mid k)=1
\]

**Estimated from data:** \(\hat p, P^L, n_k, k_r\). **ASSUMED:** hour bins 1 h LST; \(m\) in 1 °F bins; no diurnal-shape residual beyond \((M,h)\).

**Uncertainty shrink:** later `hour_lst` concentrates mass on the current rung (MDW JJA interior \(m=0\): 0.5868 at 12h → 0.7907 at 16h, `archive_table.py`). The density table must reproduce that concentration; it is not a separate σ model.

**Hard invalidation of \(P\):** if \(M^L > r.\mathrm{upper}\) (finite) → \(P(r)=0\), \(P(\text{higher rungs})\) renormalized. A later obs outside \(r\) after a fill is an *invalidation event* (§8), not a look-ahead rewrite of \(P_t\).

Wilson-lower is the **edge-test** probability. \(\hat p\) is the mean inside the uncertainty haircut \(u\). Never compare an information-conditioned ask to unconditional climatology (L-21).

### 3.3 FULL form (gated; does not exist; not registered)

Reuse `WeatherProbabilityEngine.bucket_probability` (`probability.py:328-371`): CDF of \(\mathcal N(\hat T+\mathrm{bias},\sigma(h_{\mathrm{issuance}}))\) over the closed bucket, \(\sigma=\max(0.25,\sqrt{\sigma_0^2+(\sigma_\sqrt h\sqrt h)^2})\) capped (`probability.py:245-248`). Defaults `default_conus_summer_error_model` (σ(24 h)=2.8 °F) are **ASSUMED priors**. Fit with `fit_error_model` — **not wired today (A4)**.

**NEW helper (justified):** the engine does not condition on \(M_t\). Truncated \(P(r\mid T_{\max}\ge M^L)=\frac{P(r\cap[M^L,\infty))}{P([M^L,\infty))}\). Continuity correction stays 0.5 °F.

The killed forecast family used untruncated \(P\) at 24 h vs ask 0.85 and lost the 0.06 edge (B1). FULL **does not claim 24 h interior edge**. Until forecast ingest lands, LADDER_EV **refuses `mode=full` at construction**.

### 3.4 Forecast input contract (other track, C5/C9)

No production `ForecastSource`. `ForecastSnapshot` is a plain dataclass, not Nautilus `Data`. FULL requires `OpenMeteoForecastPoint(Data)` as in `docs/plans/forecast_ingest_2026-09-01.md`: Strategy reads **only** `load_forecast_asof(..., as_of_ns=now)`. Replay key remains `ts_init` (C7); as-of filtering is `available_at_ns`. Joint quote+forecast+settlement = **zero** station-days (C9).

---

## 4. Executable price & cost model

Displayed ask is **not** the EV input (A3 does this; LADDER_EV does not).

**Fail-closed depth adapter (C7, NEW).** Shipped `ask_levels` takes a `MarketQuote` and **falls back to top-of-book** when no ladder is present (`src/breezy/strategy/weather_common/ladder.py:185-198`). LADDER_EV does **not** call it on the EV path.

```
depth_levels_from_book(book: OrderBook | OrderBookDepth10) -> list[(price, size)]
```

Returns **only real levels** (skip `size<=0` / `price<=0` padding). Raises `NoExecutableDepthError` when none remain. **No top-of-book fallback anywhere in LADDER_EV’s EV path.** Native `OrderBook` exposes levels (D1) but the Breezy cost walk needs `(price, size)` tuples and the existing helper is not fail-closed (L-1).

**Depth walk.** Reuse `walk_ask_ladder` + `depth_aware_trade_cost_prob` (`ladder.py:135-182`, `costs.py:261-342`). Do **not** use `OrderBook.get_avg_px_for_quantity` for pre-trade EV: it returns `0.0` on empty (`costs.py:220-223`).

For intended \(q\):

- `p_exec(q)` = VWAP of filled size (probability units) = `cost.executable_price`
- `p_worst(q)` = last level touched — **limit price** = `cost.worst_price`
- `p_tob` = level-0 ask = `cost.top_of_book_price`
- `fillable` = recorded size; if `depth_exhausted` and `fillable < q` → no trade (PREREG \(q=1\): need ≥1 contract of real depth)

**Fee (B3, OQ8):** \(\theta\cdot p\cdot(1-p)\), taker \(\theta=0.06\), banker's round to $0.01, **no minimum fee**. Reuse `venue_fee_prob` (`costs.py:149-177`). `FeeCoefficientSource` must raise, never default (A6). Maker rebate unused (we take).

**Slippage.** `slippage_prob` **UNMEASURED** (B5, 1-tick placeholder). Reuse `max(slippage_floor_prob, VWAP−TOB)` inside `DepthAwareTradeCost`. Default floor `0.01`. 57% of $24.53 notionals exceed L0; p90 walk 0.137 (B5 / `costs.py:271-281`) — at \(q=1\) most walks stay in L0; the floor still applies.

**Tick floor:** 0.01. Limit = `ceil_tick(p_worst)`.

**Freshness.** Reuse `RiskManager.quote_tradable` (`risk.py:467-502`): reject missing both sides, crossed, `future_quote`, `stale_quote`. One-sided **ask** is tradable for a long-YES taker; empty bid is not a 0.00 spread. `stale_quote_seconds=30` **ASSUMED** (WS push). Quote age vs **clock now**, not `tick.ts_event` as `now` (A3 defect).

**Unified cash cost (C3) — one object, used everywhere below:**

\[
C(q)=p_{\mathrm{tob}}+\mathrm{fee}(p_{\mathrm{exec}}(q))+\max(s_{\mathrm{floor}},\,p_{\mathrm{exec}}(q)-p_{\mathrm{tob}})
=\texttt{cost.top\_of\_book\_price}+\texttt{cost.total\_prob}
\]

(`costs.py:324-342`: `total_prob = fee_prob + slippage_prob`, `slippage_prob = max(floor, exec−tob)`). The base term is \(p_{\mathrm{tob}}\), **not** \(p_{\mathrm{exec}}\): the walk concession enters exactly once, through the slippage term. When the concession exceeds the floor this equals \(p_{\mathrm{exec}}+\mathrm{fee}(p_{\mathrm{exec}})\); on a flat book it equals \(p_{\mathrm{tob}}+\mathrm{fee}+s_{\mathrm{floor}}\).

**Call contract (unchanged; equals \(P^L-C\)):**

```
cost = depth_aware_trade_cost_prob(levels, q, price_scale, θ, slippage_floor_prob)
ev_net(q) = edge_after_costs(P_L, bid_p=None, ask_p=cost.top_of_book_price,
                             intent_long_yes=True, cost=cost.total_prob)
```

That is \(P^L-C\) (`risk.py:732-751`). **Do not** pass VWAP as `ask_p` and `total_prob` as `cost` (double-counts the walk). \(s_{\mathrm{floor}}\) lives **only** inside \(C\); it is **not** added again in the entry gate.

**NO-side inversion (not an order).** NO is the other side of the **same** book (B3). `submit_chain` is BUY / IOC / LIMIT / qty=1 / YES only (A8) — **do not** send `outcomeSide=NO`. “Buy the complement” = BUY YES on other rungs of the same city-day that independently clear §5. Under PREREG \(q=1\), take **at most one** such rung.

---

## 5. Edge test & minimum edge

CRH: \(P^L > \mathrm{ask} + \theta\cdot\mathrm{ask}\cdot(1-\mathrm{ask})\) at displayed ask (`decision.py:298-300`, θ=0.06). That folds fee into BE but ignores depth, quote age, and \(P\)-uncertainty beyond the frozen Wilson cell.

**Enter iff** the cell is in the DEGRADED ENTRY universe (§2) **and**

\[
P^L(r\mid\mathcal{I}_t)-C(q)\;>\;\mathrm{margin}(h,n_k)
\]

\[
\mathrm{margin}(h)=m_0+(m_{24}-m_0)\cdot\mathrm{clip}\!\left(\frac{h-h_0}{24-h_0},0,1\right)
\]

with \(m_0=0.02\) **ASSUMED**, \(m_{24}=0.06\) **pinned to B1** (honest-σ forecast family failed to clear 0.06), \(h_0=6\,\mathrm{h}\) **ASSUMED**. For \(h>24\,\mathrm{h}\) margin stays \(\ge 0.06\) **and** entry is forbidden by the DEGRADED ENTRY universe (C6). If \(n_k < n_{\min}\), refuse (infinite margin). \(n_{\min}=90\), matching the project’s Wilson-cell precedent (`scripts/analysis/mb_current_rung_edge_study.py:172`, `N_MIN=90`). Keep 40 only as a documented **sensitivity arm** in the kill script (C10).

DEGRADED: Wilson-lower already is the 95% haircut — do not subtract another \(z\cdot\mathrm{SE}\). FULL (not registered): replace \(P^L\) with \(\hat P - z\cdot\mathrm{SE}\), \(z=1.96\).

**Break-even for scoring stays** \(\mathrm{BE}=p_{\mathrm{fill}}+\mathrm{fee}(p_{\mathrm{fill}})\) (PREREG A7 / `trial_scorer.py:187`). **The margin is a policy buffer, not part of BE.**

Screen: `executable_ask_lower=0.05`, `executable_ask_upper=0.95` (`config.py:227-228`).

### 5.2 Exclusion filter (dead cells — scored for audit, never submitted)

A cell is **ineligible for ENTRY** if any hold. Audit/renormalisation still sees every rung.

| Id | Observable determination | Refuse because |
|---|---|---|
| X1 | \(M^L > r.\mathrm{upper}\) (finite) | HARD_NO. Buying 0.01 dumps on lost rungs is L-9 / B1 |
| X2 | CLI prelim or final exists for that climate day | Print-lock / post-determination (B1: 0 asks / 3332) |
| Xc | ask \(\le\) `dump_ask_max=0.03` **at any hour** | K1 is a **price-level** fact, not a time-of-day fact (B1, C4) |
| X3 | `hour_lst ≥ peak_hour_lst[station] + diurnal_peak_lag_h` AND \(P^L\le 0.05\) | Post-peak lottery already lost (L-9 amendment). Evaluated AFTER Xc; its former ask conjunct was dropped (V4) so the two reasons partition cleanly: any ask ≤ 0.03 records `dump_ask`; a post-peak near-zero-\(P^L\) cell above 0.03 records `post_peak_lottery` |
| X4 | \(P^L \ge \texttt{lock_p_max}=0.95\) | Near-certain rung; locks never offered (B1) |
| X5 | \(P\) computed without \(M_t\) when obs are required (DEGRADED, climate day started) | Climatology comparator (L-21) |
| X6 | NYC in DEGRADED ENTRY | Hourly obs (B1 / L-13) |
| X7 | `RunningMax.spans(ladder)` | Ambiguous \(M\) (`decision.py:276-277`) |
| X8 | Illegal width/\(m\) pairing (`is_legal_cell`, `decision.py:235-246`) **excluding width_code 2**, which is X11's object | Unforgeable illegal cell (L-22). Without the carve-out X8 would swallow every `lt` rung and X11 would be dead code (V6) |
| X9 | K1 cheap-open (ask ≤ 0.05 at listing, no \(M_t\)) | Dead on Kalshi exhaustive + PM tape pop 0 (B1) |
| X10 | Interior prelim→final as a *trade* (G-01 FAIL MDW/NYC/SFO) | Not an entry; revision is an invalidation input only |
| X11 | Open-lower `lt` rung (width_code 2) | Refused for ENTRY **unconditionally** (CRH `_is_legal_cell` never legalizes it; `archive_table.py` has no such keys). **Still in the partition density** for audit and renormalisation (C4) |

Plus universe gates (not X-ids, but refuse reasons): `outside_entry_window` (`hour_lst` not in `[12:00,17:00)`), `dplus1_entry` (D+1), `exception` (C13).

**Evaluation order (audit-preserving).** The X-rules are evaluated BEFORE the executable-ask screen (`executable_ask_lower=0.05`), in the order X1, X2, Xc, X3, X4, X5, X6, X7, X8, X9, X10, X11, then the universe gates, then the screen (`not_executable`) and quote gates. First match is the recorded `refuse_reason`. This differs from CRH (`decision.py:286-291` screens first) on purpose: a row refused as `dump_ask` or `cheap_open` must be countable as such in the §12 design-kill audit; screening first would collapse every ask ≤ 0.05 into `not_executable`. The ENTRY decision is identical either way.

`peak_hour_lst` **ASSUMED:** LAX 15, MDW 16, MIA 15, SFO 16, NYC 16 (LST).

---

## 6. Ranking

Premium-at-risk is the dollar unit (L-2). **Do not rank by `ev_net / p_exec`** — that structurally favours cheap lottery rungs; adverse selection concentrates in cheap cells; Xc already refuses ≤0.03 (C9).

**Primary rank** (absolute expected profit per contract; at \(q=1\) this is dollar EV):

\[
\mathrm{score}=\mathrm{ev\_net}\times(1-\lambda_u u)\times(1-\lambda_c c)
\]

- \(u = 1-P^L/\hat p\) (DEGRADED) or \(\mathrm{SE}(\hat P)\) (FULL). \(\lambda_u=1\) **ASSUMED**.
- \(c=1\) if another YES of the same city-day is already open or ranked higher this tick; else 0. \(\lambda_c=1\) plus hard cap `max_per_city_day=1` via `exclusive_conflict` on the **shared** view (`risk.py:513-526`). Six rungs are a partition: two YES on one city-day are negatively correlated, not a second independent trial.

**Tie-breaks:** higher ROI \(\mathrm{ev\_net}/C\), then smaller \(h\), then larger `fillable`, then `instrument_id` lexicographic.

**Per-tick table.** NEW `OpportunityRow(Data)` (D9 — no native ranker / EV type). Publish via `self.publish_data` for catalog/audit; rank in-process.

| Field | Type | Notes |
|---|---|---|
| `ts_event`, `ts_init` | int64 ns | event = book transactTime; init = scan fire |
| `instrument_id`, `station`, `climate_day`, `rung_bounds` | str / date / (lo,hi) | |
| `mode` | `degraded` | FULL refused at construction |
| `p_hat`, `p_lower` | float | |
| `p_exec`, `p_tob`, `p_worst`, `fee_prob`, `slippage_prob`, `C`, `ev_net`, `margin`, `score` | float | \(C\) = unified cost |
| `fillable_qty`, `depth_exhausted` | float / bool | |
| `h_hours`, `m_lower`, `n_cell` | float / int / int | |
| `in_entry_universe` | bool | §2 DEGRADED ENTRY |
| `side_expr` | `yes_rung`\|`yes_complement` | BUY-YES only |
| `eligible`, `refuse_reason` | bool / str | X1–X11, Xc, quote/obs/universe gates, `exception` |
| `rank` | int\|None | among eligible |

---

## 7. Sizing & entry

**PREREG quantity:** `order_quantity=1` (B6). Decimal `minimumTradeQty=0.01` is **UNRESOLVED** live.

**Fractional Kelly (specified, gated off), unified cost (C16):** \(f^\star=(P^L-C)/(1-C)\), \(q=\kappa f^\star B / C\), \(\kappa=0.25\), clip to operator max-per-position **read** from the ledger (never assigned). `kelly_enabled=False` until `n_live_fills ≥ kelly_unlock_n=40`. Native `FixedRiskSizer` is stop-distance, wrong unit (D3).

**Order:** native `LimitOrder` BUY, `time_in_force=IOC`, `price=p_worst` (tick-ceiled), `quantity=1`, `allow_short=False`. Construct via `self.order_factory.limit(...)` then `self.submit_order` (CRH shape, `strategy.py:542-550`). Not GTC: (i) live TIF besides IOC/GTC **NOT ESTABLISHED** (B3); (ii) IOC zero-fill is `ACCEPTED_ZERO_FILL_TERMINAL` and is **not** a trial (B4); (iii) anything else is AMBIGUOUS and burns the day (GL-4); (iv) Nautilus cannot cancel `INITIALIZED`; (v) long-only maker is rejected (B1). Not MARKET (L-25). Not FOK until live-accepted.

**Caps.** `max_simultaneous_positions=4` **ASSUMED**. `max_per_city_day=1` via `SharedExposureView` + `exclusive_conflict`. Query `self.cache.positions_open_count` / `orders_open_count` (D4) as inputs. No native max-open gate (D4).

**Daily budget.** `DailySpendLedger.spent_today_usd(now_ns)` exists (`operator_controls.py:289-299`). Remaining as a named method is **ABSENT** — add a read-only `remaining_today_usd(now_ns)` that returns operator budget minus spent and **raises if the env cap is unset** (same posture as `authorize_order_cost`, `:301-380`). Strategy skips the pick if remaining is unreadable. Exec client remains the real gate at `_submit_order` (A8). Never assign operator env caps.

One in-flight submit per strategy: AMBIGUOUS latch is account-wide (B4).

---

## 8. Exit & invalidation

**Default:** hold-to-settlement. `entry_only_halt=True` (CRH, `config.py:234`). No CRH/lock exit policy exists (A3, A9). Median exit-side depth 0.30 contracts, bid side bimodal, often empty (B5).

**Mark invalidated (record `InvalidationEvent`; do not require a flatten):**

1. \(M^L > r.\mathrm{upper}\) after fill → known loser.
2. FULL only: \(|\Delta\hat T| \ge \texttt{forecast_revision_invalidate_f}=1.5\) °F **ASSUMED**, or CLI prelim contradicts the rung.
3. `MARKET_STATE_HALTED` / listing disappearance / settlement-source anomaly.

**Audit-only exit rule (C5) — do not double-count the sunk entry fee:**

\[
\text{sell iff } P^L_{\mathrm{now}} < \mathrm{bid\_VWAP}(q) - \mathrm{fee}(\mathrm{bid\_VWAP}) - \texttt{exit\_edge}
\]

No ask-side term and **no entry-fee term** on the hold side. `exit_edge=0.015` **ASSUMED** (forecast-family constant, A4). `exit_sell_enabled=False` until live SELL-to-close is proven. `BacktestOrderGuard._refuse_naked_short` refuses a SELL that exceeds net long **including `reduce_only`** (`backtest_order_guard.py:221-244`; C6 harness). **Replay cannot exercise exits today — exits are audit-only in v2.** If the bid side is empty or size < 1: log, do nothing. Do not rest GTC. Do not buy a hedge complement. Most invalidated losers are held to $0.

---

## 9. Backtest & refinement

**Datasets (C1–C9).** Quote+depth: converted parquet 08-30..09-06 except 09-02 empty (C1, L-20). CLI live finals 18–19/station from 2026-08-16 (C2). Archive CLI 9,185 days = **calibration**, not a price backtest (C3). Forecast+quote+settlement joint = **zero** station-days (C9).

**Joint window today:** quote+CLI from 2026-08-30; 7 converted dates; ~151 instrument-days.

**ts_init:** Nautilus sorts on `ts_init` only (C7, D7). Obs = receipt; CLI live = retrieval; archive CLI = issuance; forecast as-of = `available_at_ns`.

**Fills:** C6 harness — L2_MBP, `liquidity_consumption=True`, `FillModel()` inert under L2, `PolymarketUSFeeModel()` post-fill (`backtest_harness.py:713-745`). QuoteTick does not mutate the book. Fills only from recorded Depth10. IOC remainder cancelled. Price improvement → `ImpossibleFillPriceError` (L-25). Never fill more than resting size at that timestamp.

**Latency / fill timing (C8).** Harness sets `latency_model=None` (known overstatement, `backtest_harness.py:727-745`). L-25 showed same-timestamp ordering produced impossible fills. **Rule:** a decision at scan time \(t\) may fill only against the first `OrderBookDepth10` with `ts_init ≥ t + reaction_latency_s` (default `1.0` s **ASSUMED**), **never** the snapshot that produced the decision. Kill script **must** run a latency sensitivity (1 s / 5 s / 30 s). **Zero-latency results are optimistic and non-operative** — preregistered as such.

**Settlement truth for scoring (C11).** Pin to the CLI FINAL that was **available at the venue’s settlement time** (08:00 ET D+1; METAR-conflict 11:00 ET): `revision_seq` of the last FINAL with `retrieved_at_ns ≤ venue_settlement_ns`. Later corrections are logged (CF-13) and **do not rewrite `held`**. This **differs** from the sibling whole-tape driver’s highest-revision rule (C8 LOOK_AHEAD_CAVEAT): a correction that arrived after the venue settled is information the bot could not have had; rewriting `held` after the fact contaminates the PREREG statistic.

**Archive vs tape.** Archive learns \(P^L(\cdot\mid k)\) only. Offered-ask selection, adverse selection, and slippage are **only** on the live/converted tape (B2).

**Eval statistic:** reuse v2 / PREREG (B6, A7): per-row \(S_k=\sum(\mathrm{held}_i-\mathrm{BE}_i)/\sqrt{\sum \mathrm{BE}_i(1-\mathrm{BE}_i)}\), \(\mathrm{BE}=p_{\mathrm{fill}}+\mathrm{fee}\). `score_trial` (`trial_scorer.py:150-208`) unchanged except the **caller** must pass the settlement-time FINAL (C11), not `final_tmax_f` of the highest revision. Paper vs live never pooled.

**Overfit guards.** Freeze the last 2 converted dates as holdout (currently 09-05, 09-06 — **re-pin at registration**). One look per rule/table/threshold change; that change **is a new family**, n resets (B6). Do not retune on holdout. Do not weaken X1–X11 / Xc to raise fill count.

### 9.1 PREREG (register before first fill) — live gating, v2 realized-information solver

- **Hypothesis:** §1 sentence.
- **Trial:** filled \(q=1\) IOC BUY-YES Take only. Not skip-days, zero-fills, AMBIGUOUS, \(q\neq 1\), paper, shadow, archive, Kalshi (B6).
- **Looks:** every 10 filled takes, \(n=10..160\). \(I_{\max}=40\), two one-sided \(\alpha=0.025\), Lan-DeMets O’Brien-Fleming. **Per-row** \(S_k\), \(I_k=\sum\mathrm{BE}_i(1-\mathrm{BE}_i)\), boundary at **realized** \(t\) (B6).
- **KILL:** \(S_k\le b^{\mathrm{fut}}\) or cell_dead or \(\sum\mathrm{PnL}\le -60\) or structural-dead (0 fills on ≥15 afternoon-covered listed station-days).
- **SURVIVE:** \(S_k\ge b^{\mathrm{eff}}\) AND \(\sum\mathrm{PnL}>0\) AND no cell_dead. D0+165 terminal.
- Operator-only: max daily budget, max per position, enablement, positive control. G-02 ROI NO-GO (B7) is **acknowledged**, not waived.
- The §12 offline script is a **DESIGN kill, non-operative for live.** Live gating uses **only** this block.

### 9.2 Validity caveats (C14)

- DEGRADED backtest running-max input is **SYNTHESIZED receipt** (observed + 30/45 min lag from IEM ASOS CSV, C4), **not** measured live receipt.
- Per-tick cost of 60 Depth10 walks every 15 s is **UNMEASURED**. The kill script **must** report wall-clock and peak RSS per tick (unit-memory-cap history).

---

## 10. Machine-executable decision procedure

```
on_start:
  ids = catalog.instruments() ∩ HIGH ∩ {D, D+1}   # no climate_day==today filter
  self.subscribe_order_book_depth(ids)
  self.clock.set_timer("scan", scan_interval_s, callback=on_scan, fire_immediately=True)
  self.clock.set_timer("rediscover", rediscover_interval_s, callback=on_rediscover)

on_rediscover:                                 # entire body try/except → log + scan_exception_count++ (L-16)
  desired = HIGH ∩ {D, D+1} from self.cache.instruments(venue=POLYMARKET_US)
  subscribe new; unsubscribe gone              # NO venue GET

on_scan(now_ns):                               # entire body try/except → log + scan_exception_count++
  if submit_intent latch OPEN: return          # GL-4, account-wide
  if self.cache.positions_open_count() + orders_open >= max_simultaneous_positions: return
  remaining = ledger.remaining_today_usd(now_ns)   # skip scan-picks if unreadable; do not assign caps
  rows = []
  for id in subscribed:
    try:
      book = self.cache.order_book(id); facts = WeatherBucketFacts(id)
      M, stale = running_max(facts.station)
      P_hat, P_L, n_cell = density_table(facts, M, now_ns)   # DEGRADED only
      levels = depth_levels_from_book(book)                 # NOT ask_levels; raises NoExecutableDepthError
      cost = depth_aware_trade_cost_prob(levels, order_quantity, 1.0, θ, slippage_floor_prob)
      if not quote_tradable(...): refuse; continue
      C = cost.top_of_book_price + cost.total_prob
      ev = edge_after_costs(P_L, None, cost.top_of_book_price, True, cost.total_prob)  # = P_L - C
      elig, reason = exclusion_filter(...)  # X1–X11, Xc, universe gates
      u = 1 - P_L/P_hat
      score = ev * (1-λ_u*u) * (1-λ_c*c) if elig else None
      rows.append(OpportunityRow(...)); self.publish_data(OpportunityRow)
    except Exception:
      rows.append(OpportunityRow(eligible=False, refuse_reason="exception")); continue
  eligible = sort(rows where elig and ev>0, key=score, tiebreaks §6)
  apply max_per_city_day=1 via SharedExposureView
  pick = first row with (P_L - C) > margin(h, n_cell)
      and in DEGRADED ENTRY universe
      and cost.fillable >= order_quantity
      and C * q <= remaining
      and SharedExposureView net_qty(city-day)==0
  if pick is None: return
  if not kelly_enabled: q = 1
  order = self.order_factory.limit(BUY, IOC, price=tick_ceil(pick.p_worst), qty=1)
  self.submit_order(order)   # live body: BUY/IOC/LIMIT/qty=1/YES
```

**`LadderEvConfig(StrategyConfig, frozen=True)`** fields. Operator dollar caps **absent**. `allow_short=False` immutable. `mode='full'` raises at construction.

| Field | Default | Unit |
|---|---|---|
| `scan_interval_s` | 15 | s **ASSUMED** |
| `rediscover_interval_s` | 300 | s **ASSUMED** |
| `stale_quote_seconds` | 30 | s **ASSUMED** |
| `stale_observation_minutes` | 50 | min |
| `executable_ask_lower` / `_upper` | 0.05 / 0.95 | prob |
| `order_quantity` | 1 | contracts |
| `min_fillable_qty` | 1.0 | contracts |
| `slippage_floor_prob` | 0.01 | prob **UNMEASURED** |
| `required_fee_coefficient` | 0.06 | 1 (must match live info) |
| `dump_ask_max` | 0.03 | prob |
| `lock_p_max` | 0.95 | prob |
| `diurnal_peak_lag_h` | 1 | h **ASSUMED** |
| `peak_hour_lst` | see §5.2 | hour LST **ASSUMED** |
| `n_min_cell` | 90 | counts (C10) |
| `margin_m0` | 0.02 | prob **ASSUMED** |
| `margin_m24` | 0.06 | prob (pinned B1) |
| `margin_h0_hours` | 6 | h **ASSUMED** |
| `reaction_latency_s` | 1.0 | s **ASSUMED** (C8) |
| `uncertainty_penalty` | 1.0 | 1 **ASSUMED** |
| `max_simultaneous_positions` | 4 | count **ASSUMED** |
| `max_per_city_day` | 1 | count |
| `kelly_enabled` | False | bool |
| `kelly_fraction` | 0.25 | 1 |
| `kelly_unlock_n` | 40 | live fills |
| `entry_only_halt` | True | bool |
| `allow_short` | False | bool |
| `nyc_degraded_excluded` | True | bool |
| `dplus1_require_running_max` | True | bool |
| `forecast_revision_invalidate_f` | 1.5 | °F **ASSUMED** |
| `exit_edge` | 0.015 | prob **ASSUMED** |
| `exit_sell_enabled` | False | bool; audit-only in v2 |
| `mode` | `degraded` | enum; `full` refused |
| `raw_corpus_pin` | CRH corpus SHA | hex; pins the RAW archive bytes CRH's selector was built from (`generate_current_rung_hold_archive_table.py:115-125`), NOT a hash of the 6-rung table — the on-disk 6-rung freeze is NOT RUN (stage 2); the field is a placeholder gate until a frozen-table hash exists (V5) |
| `se_z` | 1.96 | 1 (FULL only; unused) |

Runtime latch (not a config field): `scan_exception_count` (C13). Kill-script-only arm: `n_min_cell=40` (not live).

---

## 11. Native reuse map

| Component | Reuse | NEW? |
|---|---|---|
| Scan / rediscovery timers | `self.clock.set_timer` (D6) | no |
| Multi-book subscribe, levels | `self.subscribe_order_book_depth`, `self.cache.order_book` (D1) | no |
| Instrument seed | `ParquetDataCatalog.instruments` (D7) + `self.cache.instruments(venue=POLYMARKET_US)` | **no new venue client** (C1). GL-8 reload clamp is DataClient, separate track |
| Running max / obs | `RunningMax`, `StationObservation` (C4) | no |
| Bucket bounds | `WeatherBucketFacts` / `MispricingContract` (A6) | no |
| Forecast CDF (FULL) | `WeatherProbabilityEngine.bucket_probability` + `fit_error_model` (A4) | no; not this family |
| Truncate CDF on \(M_t\) | engine has no truncator (`probability.py:328-371`) | **NEW** — L-1; FULL-only, other track |
| 6-rung archive density + Wilson | `P_HOLD_LOWER` is current-rung selector only (A2) | **NEW** — L-1: not a density |
| Fail-closed depth tuples | native `OrderBook` levels (D1); shipped `ask_levels` TOB-falls-back (`ladder.py:185-198`) | **NEW** `depth_levels_from_book` — L-1: helper not fail-closed |
| Depth EV / fee | `walk_ask_ladder`, `depth_aware_trade_cost_prob`, `venue_fee_prob`, `edge_after_costs` (A6) | no (call contract §4; \(C=\) tob+total_prob) |
| Quote gates / exclusive YES | `quote_tradable`, `exclusive_conflict` + `SharedExposureView` (A6, C2) | no |
| Ranker + `OpportunityRow` | none (D8/D9, A9) | **NEW** — L-1: D9 genuine gap |
| Pre-trade probability cost | `FeeModel` is post-fill (D2/D9) | no extra — A6 already fills the gap |
| Sizer | `FixedRiskSizer` wrong unit (D3); Kelly=0 in repo | **NEW** Kelly with \(C\), **gated off** |
| Daily budget / pos cap | `DailySpendLedger.spent_today_usd` (`operator_controls.py:289-299`); remaining accessor **ABSENT** | add read-only `remaining_today_usd` |
| City-day net qty | not `cache.net_qty`; `SharedExposureView` (`risk.py:393-465`) | no |
| Orders | native `LimitOrder` IOC via `order_factory.limit` + `self.submit_order` (D5) | no |
| Submit shape | existing BUY/IOC/LIMIT/YES chain (A8) | no |
| Replay / fees / no improvement | C6 harness | no |
| Trial PnL / \(S_k\) | `score_trial`, family tally (A7, B6) | caller pins settlement-time FINAL (C11) |
| Forecast Data + as-of catalog | plan only (C5) | **NEW type, other track** — prerequisite, not this family |
| Bid-walk for exit | `walk_ask_ladder` is ask-only (`ladder.py:135`) | **NEW sibling iff `exit_sell_enabled`** — L-1; audit-only in v2 |
| Timer exception latch | CRH alerter swallow (`strategy.py:495-498`); L-16 | wrap entire `on_scan`/`on_rediscover` (C13) |

---

## 12. Risks, open questions, cheapest kill

**Risks.** (1) Forecast family already died at honest σ≈2.8 °F / 24 h (B1) — DEGRADED may be the *only* live mode, and it is M_B-plus-ranking, not a new information source. (2) Offered-population adverse selection unmeasured (B2; ~245 offered settlements needed for the CLI-basis tail). (3) G-02 ROI NO-GO still standing (B7); positive \(S_k\) at \(q=1\) can still fail dollar ROI. (4) Converted tape is 7 dates / ~151 instrument-days (C9) — underpowered for ranking rules. (5) `slippage_prob` UNMEASURED (B5). (6) One AMBIGUOUS take kills the day (B4); scanner must not spray IOC. (7) Bid-side often empty — invalidation without exit is the common path (§8); exits unexercisable in replay (C5). (8) Open contradictions (B8): “median bid 0.3” mixes two populations; L-9 “never offered” is post-peak while M_A shows pre-lock winner asks exist (n=4). (9) Universe bounded by DataClient reload cadence (C1). (10) Concurrent live CRH + LADDER_EV contaminates PREREG (C2). (11) Synthesized obs receipt in replay (C14). (12) Per-tick 60-book walk cost UNMEASURED (C14).

**Open (NOT ESTABLISHED).** Live decimal qty; TIF other than IOC/GTC; live SELL-to-close / `reduce_only`; `GreeksCalculator` on `BinaryOption`; production `ForecastSource`; joint quote+forecast day.

**Cheapest measurement that kills the family (DESIGN kill, non-operative for live — C12).** Script under `scripts/analysis/`, reusing the whole-tape driver’s instance classification (CLEAN/EMPTY/LIVE/CORRUPT). On converted Depth10+CLI (08-30..09-06, hold out 09-05..09-06), run §10 DEGRADED with frozen archive density, X1–X11+Xc, \(q=1\), IOC at `p_worst`, fills only against recorded size **and** the §9 fill-timing rule.

**Pre-check, before any fill simulation:** count afternoon-covered listed station-days in the **train** window (7 converted dates minus 2 holdout, 09-02 empty, NYC out, ~9% skip-days). **If that count < 15, the structural-dead branch is UNREACHABLE and the result is INSUFFICIENT DATA, not KILL.** Report eligible rows and simulated fills **per station-day first**, plus wall-clock and peak RSS per tick (C14). Run latency arms 1 s / 5 s / 30 s; zero-latency is optimistic/non-operative (C8). Optional sensitivity: `n_min_cell=40` (C10).

**DESIGN KILL without going live if:** (a) station-day count ≥ 15 **and** 0 simulated fills on ≥15 such days (structural-dead, B6), or (b) mean `ev_net` of filled takes \(\le 0\) on the train dates. Do **not** use “Wilson-upper of hit rate < mean BE at n=10” — that wording is replaced; live gating is **only** §9.1’s realized-information solver. If the design kill does not fire and data are sufficient, register PREREG §9.1 before the first live fill.

---

## 13. Build contract

Makes §10 machine-executable against the real tree. Nautilus Trader is immutable; `allow_short` stays `False`; never weaken or delete a safety/settlement/contract test; never assign operator-reserved controls; never touch live-trading enablement or the NO-SEND execution-egress firewall.

**Module layout**

```
src/breezy/strategy/ladder_ev/
  config.py          LadderEvConfig(StrategyConfig, frozen=True); fields = §10 table
  density_table.py   6-rung P(r|k) + Wilson; corpus SHA pin
  depth_adapter.py   depth_levels_from_book; NoExecutableDepthError; no TOB fallback
  scoring.py         C(q), margin(h), ev_net call contract, rank/tie-break, OpportunityRow
  decision.py        X1–X11+Xc+universe gates; ENTRY vs audit
  strategy.py        LadderEvStrategy; timers; scan/rediscover
  composition.py     build_ladder_ev_strategies
```

**Tests** live under `tests/strategy/ladder_ev/` (collected by `testpaths = ["tests"]`); this starts a `tests/strategy/<package>/` convention for strategy packages — follow it for the next package rather than re-deciding.

**Constructor dependencies (injected, not imported from a live client):**

- `FeeCoefficientSource` (must raise, never default)
- running-max provider (`RunningExtremeAccumulator` / `RunningMax`)
- raw corpus pin (`raw_corpus_pin`; refuses mismatch; NOT a 6-rung table hash until the frozen build exists — V5)
- ledger reader (`DailySpendLedger`; `spent_today_usd` exists; add read-only `remaining_today_usd` or skip if absent)

**Exact native calls (no wrappers that hide them):**
`self.subscribe_order_book_depth`, `self.cache.order_book`, `self.cache.instruments`, `self.cache.positions_open_count`, `self.clock.set_timer`, `self.submit_order` of a `LimitOrder`, `self.publish_data`.

**Pseudocode name replacements**

| v1 name | v2 replacement |
|---|---|
| `venue_list(...)` | `self.cache.instruments(venue=POLYMARKET_US)` diff vs subscribed set |
| `read_ledger_remaining` | `DailySpendLedger.spent_today_usd` exists (`operator_controls.py:289-299`); remaining accessor **absent** — add read-only `remaining_today_usd` that raises if the operator cap is unset |
| `cache.net_qty(city-day)` | `SharedExposureView` (`risk.py:393-465`) |
| `ask_levels(book)` | `depth_levels_from_book(book)` (`depth_adapter.py`) |

**Composition (`app/trade.py`).** Add `build_ladder_ev_strategies` **alongside** `build_current_rung_hold_strategies` at `app/trade.py:180-193`, selected by a family flag. **Never both live** on the same account (§2.4). Shadow/replay may run LADDER_EV with `OrderSubmissionPermit=None`.

**Replay / kill-script entry:** `scripts/analysis/ladder_ev_design_kill.py` (name flexible) reusing the whole-tape driver’s instance classification. Reports: afternoon-covered station-day count, eligible rows and fills per station-day, wall-clock + peak RSS per tick, latency arms, `n_min=90` primary / `n_min=40` sensitivity.

**Tests (RED first)**

1. Density-table partition sums to 1 per key \(k\).
2. X1–X11 and Xc each refuse a constructed cell (X11: `lt` refused for ENTRY, still in density).
3. \(C(q)\) equals `cost.top_of_book_price + cost.total_prob` from `DepthAwareTradeCost`.
4. `margin(h)` values: h=6 → 0.02; h=12 → \(0.02+0.04\cdot(6/18)\approx 0.0333\); h=24 → 0.06; h=48 → 0.06.
5. `depth_levels_from_book` with empty/padded book raises `NoExecutableDepthError` (no TOB fallback).
6. `on_scan` swallows a per-instrument exception (`refuse_reason="exception"`; scan continues; `scan_exception_count` increments on body-level raise).
7. Fill-timing rule rejects same-snapshot fills (`ts_init < t + reaction_latency_s`).
8. Settlement-truth pin ignores post-settlement corrections (`retrieved_at_ns > venue_settlement_ns` does not rewrite `held`).
9. Exclusion order: a 0.02-ask cell records `dump_ask` (Xc), not `not_executable`; a 0.04-ask cell at listing with no running max records `cheap_open` (X9).

---

## 14. Change log vs v1

| Id | Where | Change |
|---|---|---|
| C1 | §2/§10/§11 | Strategy listing poll **removed**. Rediscover = `cache.instruments` diff. No new venue client. GL-8 reload clamp is DataClient, separate track; currency bounded by 21600 s cadence (`data.py:264`). |
| C2 | **NEW §2.4** | SHADOW/REPLAY while CRH live. Live requires one `SharedExposureView` or CRH retired + operator enablement. AMBIGUOUS is account-wide; concurrent live families contaminate PREREG. |
| C3 | §5 | Unified \(C=\) tob+`total_prob`. `s_floor` **removed from δ** (was double-counted). ENTRY = \(P^L-C>\mathrm{margin}(h)\). Margin interpolates 0.02→0.06 over 6–24 h. Margin is **not** part of BE. |
| C4 | §5.2 | Xc: ask≤0.03 **any hour**. X3 kept as additional post-peak rule. **X11:** `lt` refused for ENTRY, kept in density. |
| C5 | §8 | Sell iff \(P^L < \mathrm{bidVWAP}-\mathrm{fee}-\texttt{exit\_edge}\); no entry-fee on hold side. `exit_sell_enabled=False`. Replay cannot exercise exits (`BacktestOrderGuard` refuses naked SELL incl. reduce_only). Audit-only in v2. |
| C6 | §2/§3/§5 | Split universe: scored 60 vs DEGRADED ENTRY (4 stations, D only, `[12:00,17:00)` LST, \(M_t\) present unspanning). D+1 audit-only. Family **registers DEGRADED-only**. |
| C7 | §4/§11 | NEW `depth_levels_from_book`; raises; **no TOB fallback** on EV path. L-1 vs `ask_levels` (`ladder.py:185-198`). |
| C8 | §9 | Fill only vs first Depth10 with `ts_init ≥ t + 1.0s` **ASSUMED**. Latency arms 1/5/30 s. Zero-latency non-operative. |
| C9 | §6 | Primary rank = dollar EV `ev_net×(1−λu u)×(1−λc c)`; tie-break ROI `ev_net/C`, then \(h\), fillable, id. |
| C10 | §5/§10 | `n_min_cell=90` (`mb_current_rung_edge_study.py:172`). 40 = kill-script sensitivity only. |
| C11 | §9 | Settlement truth = last FINAL with `retrieved_at_ns ≤ venue_settlement_ns`. Later corrections log-only. Diverges from whole-tape highest-revision (LOOK_AHEAD_CAVEAT) **because** post-settlement rewrites contaminate PREREG. |
| C12 | §12 | Pre-check afternoon station-days; **<15 → INSUFFICIENT DATA, not KILL**. Per-station-day fills first. §12 = DESIGN kill; live = §9.1 \(S_k/I_k\) solver. Dropped “Wilson-upper of hit rate < mean BE at n=10”. |
| C13 | §10 | Entire `on_scan`/`on_rediscover` try/except + `scan_exception_count`. Per-instrument `refuse_reason="exception"` (pattern `strategy.py:495-498`). |
| C14 | §9.2 | Synthesized obs receipt (C4). Per-tick 60-walk cost **UNMEASURED**; kill script reports wall-clock + peak RSS. |
| C15 | **NEW §13** | Module layout, config, ctor deps, native calls, name replacements, `app/trade.py` family flag, kill-script path, RED test list. |
| C16 | §3.2/§7 | Density = CRH keying, 6-rung distribution, corpus SHA; estimated vs assumed stated. Kelly \(f^\star=(P^L-C)/(1-C)\), still gated off. |

Unchanged in substance: §4 call contract; BUY/IOC/LIMIT/qty=1/YES; `allow_short=False`; operator caps unread-assignable; hold-to-settlement default; archive-vs-tape split; G-02 acknowledgement.

**Convergence pass (2026-09-07, prediction-market-reviewer, NOT CONVERGED → fixed inline):**

| Id | Where | Correction |
|---|---|---|
| V1 | §2.4 | CRH does not use `SharedExposureView`; live coexistence option (a) requires retrofitting live CRH (out of §13 scope, a B6 family change) — stated honestly. |
| V2 | §4 | \(C(q)\) display formula had \(p_{\mathrm{exec}}\) as the base term (double-counted the walk); corrected to \(p_{\mathrm{tob}}\). Call contract and §13 test 3 were already correct. |
| V3 | §5.2 | X-rules evaluated before the 0.05 screen so `dump_ask`/`cheap_open` remain auditable refuse reasons; §13 test 9 added. |

**Stage-1 implementation review corrections (2026-09-07, python-reviewer + prediction-market-reviewer on the code):**

| Id | Where | Correction |
|---|---|---|
| V4 | §5.2 | Xc is evaluated before X3 unconditionally (spec order restored); X3's ask conjunct dropped so `dump_ask` and `post_peak_lottery` partition the audit cleanly. |
| V5 | §10/§13 | `archive_table_pin` → `raw_corpus_pin`: it pins CRH's raw corpus bytes, not a 6-rung table; the 6-rung on-disk freeze is NOT RUN and is stage-2 work. |
| V6 | §5.2 | X8 excludes width_code 2 (the `lt` rung) so X11 is reachable; the implementer's carve-out is ratified. |
| V7 | §13 | `is_legal_cell` made public in `current_rung_hold/decision.py` (alias + `__all__`, no rename of call sites) instead of importing a private name. |
