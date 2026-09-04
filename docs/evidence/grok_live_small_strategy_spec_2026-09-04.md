<!-- date: 2026-09-04 (UTC) -->
<!-- command: grok --prompt-file .../grok_live_small_brief.md --permission-mode plan --disallowed-tools spawn_subagent,run_terminal_command (direct rerun; plugin run run-mtm9nl9j-knyh0v failed twice upstream) -->
<!-- outcome: exit 0, 16902 bytes, model grok-4.6 -->

I'll write the live-small strategy spec from the cited evidence and code, without spawning agents or changing files. First I'm reading the ground-truth memos, lessons, risk gates, and the M_B trial definition.Next I’ll pull the lessons, risk gates, M_B trial definition, and existing strategy packages so the spec can name exact entry, size, and kill rules.I’ll now pin the exact M_B taken-trial join, the relevant lessons, and how `running_extreme_lock` already handles entry-only halt.I still need the exact taken-trial predicates, halt behavior, and order/TIF conventions so the spec can name them without guesswork.I have the taken-trial definition, risk-gate order, and halt pattern. Spec below is the one live-small strategy to implement.

# Spec: `current_rung_hold` — live-small M_B taken trials

**Status:** implementable as written. **Not** a GO on live enablement, NO-SEND, or operator caps. Those stay unset/untouched. This package places the M_B **taken** set as 1-lot taker IOC buys and holds them to CLI settlement so the pre-registered Wilson test can run on **real fills**.

Invariants: Nautilus immutable; `allow_short=False`; no safety/settlement/contract test weakened; do not assign max daily budget or max per position; no live-enablement / NO-SEND change.

---

## 0. Thesis (one sentence)

Buy YES on the **current** 2°F rung that 5-min ASOS running-max `R(t)` sits in, at the first lagged executable afternoon ask in `(0.05, 0.95)` whose **archive** Wilson-lower `p_hold` exceeds `ask + 0.06·ask·(1−ask)`, size 1, hold to settlement; **evidence** is the realized hold rate of those fills, not the archive number (L-21; `docs/evidence/grok_mb_kill_amendment_2026-09-02.md`).

---

## 1. Entry — exact M_B taken-trial definition

**No filter deviation.** Do not add month, morning-ΔT, forecast, or “skip the cheap band after MDW 09-01.” Kill-amendment: that is a new measurement, not an M_B resurrection.

| Item | Value | Source |
|---|---|---|
| Stations | Dense 5-min only: **LAX, MDW, MIA, SFO**. **NYC out** (hourly ASOS; L-13). | `DENSE_STATIONS` via `CONTAMINATED_STATIONS` in `scripts/analysis/cli_basis_offer_gate_scan.py`; `mb_current_rung_edge_study.py:75` |
| Window | Local-**standard** `[12:00, 17:00)` LST, half-open. Fixed winter offset, never IANA/DST. | `ma_prelock_winner_ask_study.py:148-150`; `climate_day.py:24-35` |
| One trial / station-day | First snapshot that passes the taken filter. If it fails, **do not search later**. | `is_taken_trial` / `gather_taken_trials` `mb_current_rung_edge_study.py:633-667` |
| Current rung | `rung_containing(real venue ladder, R(t))` — **not** the ex-post CLI winner (M_A survivorship). Interiors closed `[A, A+1]`; `m = R − A`. | `h4_preliminary_economic_read.py` `Rung`; design memo geometry |
| Legal cells | interior `m=0`, or `open_upper`. **Never** `m=1`, `open_lower`, or archive `n/a` (`n<90`). | `_cell_is_dead_by_construction` `:624-630`; Part A pre-filter |
| Ask band | `0.05 < ask < 0.95`. Bands for scoring only: `(0.05,0.15]`, `(0.15,0.30]`, `(0.30,0.95)`. | `ASK_QUALIFYING_*`; `classify_ask_band` `:411-424` |
| K-depth | level-0 `ask_sz ≥ 1.0` | `MIN_EXECUTABLE_SIZE = 1.0` |
| Selector (not evidence) | `edge = p_hold_lower(station, season, hour_lst, width, m) − BE(ask) > 0`, `BE(a)=a+0.06·a·(1−a)` | `break_even` `:176-178`; frozen Part A table in `docs/evidence/mb_current_rung_edge_2026-09-02.md` |
| Max ask | **&lt; 0.95** (not 0.99). | taken screen |
| Min `p_hold_lower` | **strictly &gt; `BE(ask)`** at that snapshot. No extra margin. | `is_taken_trial` |

**`R(t)` data source.** Paper: 5-min IEM ASOS on disk, `rounded_f`, `valid ≤ t` (`running_max_at` `h4_preliminary_economic_read.py:336-347`). **Live cannot use that cache.** Intraday ingest **is required (BL-24)**. Operator lifted the M_B gate on BL-24 (`docs/plans/BL24_LIVE_RT_2026-09-04.md`). Strategy **consumes** `StationObservation` + online accumulator; it does not fetch IEM itself. Predicate (BL-24 A1): `R(t) = max{rounded_f : measurement ≤ t and receipt ≤ t}`; **do not lag R**.

**Do not** read `NwsClimateDay` preliminary `tmax_f` (`running_extreme_lock` does; that is the L-9 lock family, 300 s CLI poll, wrong signal).

**Lag = 15 minutes, on the ASK, not on R.** Paper: `R` at `t` unlagged; entry ask = first Depth10 with `ts_event ≥ t + lag` (`find_lagged_entry` `:466-508`). Live (BL-24 A1): price only against a quote with `ts_event ≥ (receipt of the observation that last set R) + 15 min`.

Why 15 not 10: family SURVIVE already requires lags 10 **and** 15 to agree; live should implement the stricter of those two. IEM poll is ≥300 s; IEM-vs-public lag is **UNVERIFIED**. 10 min is two poll cycles of headroom — that is the cancel race L-9 says the MM wins. 5 min is paper-only sensitivity, not live.

**Hour/season for table lookup:** LST hour of observation instant `t` (the `R` time), not the quote’s hour; `season_for(climate_day)`. Ship Part A as a **frozen module constant** (same reason `running_extreme_lock` cannot import `scripts/` — `strategy.py:35-72`).

**Coverage floor:** ≥30 min Depth10 is an **ex-post scoring** rule (`MIN_AFTERNOON_COVERAGE_MINUTES`), not a live entry gate (you cannot wait until 17:00 to know it). Enter on the first taken-qualifying snapshot in-window. If the day ends with &lt;30 min coverage, **drop from Wilson n**; the fill still holds. Log `n_filled` vs `n_scored`.

---

## 2. Order type and price

- **BUY YES only.** `OrderSide.BUY`. `post_only=False`. Never `participateDontInitiate`. Never an unpriced `MARKET` (walks the book; `cli_settlement_print_lock/strategy.py:66-74`).
- **Marketable LIMIT at the displayed level-0 ask**, snapped with `instrument.make_price`. **Not ask+1 tick** — qty=1 and `ask_sz≥1` means the screen’s price is fillable; +1 tick is a different (worse) price than M_B scored.
- **TIF = IOC.** GTC would rest a bid if the ask lifts — a maker bid on the current rung, rejected in `docs/evidence/grok_no_edge_verdict_2026-09-02.md` §1b, and `MakerRebateUnmodelledError` makes maker fills unevaluable (`fees.py:172-193`).
- **IOC miss:** consume the station-day. Log `ioc_miss`. **Do not retry** (that is afternoon snapshot-shopping). Unfilled → not in Wilson n.
- **Partial fill:** learn page says no fractional contracts; API may advertise `minimumTradeQty&lt;1` (`DOCS_RECHECK_2026-09-03.md`). If `minimumTradeQty &gt; 1` on a market, **refuse that market** (do not size up). If a fraction fills: **hold the filled qty**, do not send remainder (no retail idempotency key; R-7 latch is the only double-send guard). Score on filled qty.
- **Never a resting SELL.** Never any SELL. Settlement pays $1/$0. Flatten-into-bid is forbidden (T-9).

---

## 3. Size

**1 contract per trial.** Argue otherwise: no. This is a measurement; 1 lot is the smallest whole contract the learn page and K-depth agree on. Cash at ask 0.06 ≈ $0.06 + ~$0.00–0.01 fee; at 0.65 ≈ $0.65 + fee. No venue max size (`DOCS_RECHECK`).

**Trials / station-day:** **one**. Max concurrent entries = number of listed dense stations that day (≤4). Exclusive-YES already forbids two rungs on the same climate day (`risk.py:370-377, 450-463`).

**Operator caps (do not set them):** when the operator later sets max-per-position / max-daily-budget, this strategy sends 1 lot only if both still allow ≥1 contract after already-committed exposure that day; else refuse and log. Do not clip to a fraction and round up. Existing `RiskLimits.max_position_contracts=250`, `max_event_notional=1000`, `max_location_notional=2000`, `max_simultaneous_positions=12` do not bind at 1 lot — leave defaults; do not use them as a substitute for the unset operator controls.

---

## 4. Exit (T-9)

- **Hold to settlement.** No take-profit, no stop, no flatten.
- **Entry-only halt:** copy `running_extreme_lock/strategy.py:337-342` — when `hours_to_settlement ≤ halt_hours_before_settlement` (default 1.0 h vs native `expiration_ns`), **return**; do not `_flatten` / `close_all_positions`. Forecast-family flatten is the wrong policy on a ~0.3-lot bid.
- **Never exit into the bid.** Median TOB bid 0.3 contracts; dumping a near-certain long destroys settlement value.
- Horizon from **clock + `expiration_ns`**, never `ForecastSource` (T-5/T-7/T-8; T-10 argument-order trap). Window `[12:00,17:00)` LST is ≫ 2 h before 08:00 ET next morning, so `min_hours_to_settlement=2.0` and `halt=1.0` are **inert in-window**; keep as backstops, do not retune (T-9: 1.0 h is unverified).

---

## 5. Data freshness / no-trade

| Condition | Action | Who enforces |
|---|---|---|
| Quote age &gt; `stale_quote_minutes=15` or quote in the future | refuse `stale_quote` / `future_quote` | `evaluate_order` / `quote_tradable` |
| No current-climate-day observation, or gap &gt; `stale_observation_hours` | refuse; no synthesised R | decision-layer `observation_unavailable` (BL-24 A4); risk `stale_observation` / `observation_limit_unset` |
| Observation timestamp ahead of clock | refuse `future_signal` | `evaluate_order` |
| Missing ASOS / unparseable METAR | drop-and-count (L-17); R unchanged; staleness rises until refuse | BL-24 ingest, not strategy |
| Venue skip-day (~9% of listed days; 09-02 never existed) | no instruments → no trial, **not a miss**, not a Wilson 0 | discovery zero-universe guard; `MISSING_COHORT_2026-09-02_2026-09-03.md` |
| Market close / after 17:00 LST / halt window | no new entry | strategy window + halt |
| Quiet book (MIA 09-01: 0 afternoon depth) | no snapshot → no order | natural |

**`stale_observation_hours` must be set.** Default `None` refuses every OBSERVATION order (`risk.py:137-138, 529-531`). Set **0.5 h** (30 min ≈ six missed 5-min cycles). Do **not** use `running_extreme_lock`’s ~12.7 h CLI-issuance candidate. Construction raises if `None` (same as `MissingObservationBoundError`). Age = hours since observation **measurement/issuance**, not ingest (`freshness.py:55-58`). `assumed_publication_lag_ns` is provenance only — never subtracted (BL-24 A6).

**Ask-only `MarketQuote` into `evaluate_order`.** If both sides are populated, `quote_tradable` uses `min(bid_sz, ask_sz)` and a spread check (`risk.py:409-416`). Weather books often have a ~0.3-lot bid vs a 0.21 ask → `insufficient_liquidity` / `wide_spread` would **systematically refuse the M_B taken set**. A long-only taker pays the ask; pass `bid=None`. Do not raise global `max_bid_ask_spread`.

**Equity:** `evaluate_order` refuses `equity_unobserved` / `equity_nonpositive` on buys (T-4). Live wiring must `query_account` so equity is observed. Spec does not fabricate a default.

---

## 6. Pre-registered evaluation (encode before the first fill)

**Unit of inference:** one filled taken trial per station-day. Snapshot-weighted pools forbidden. Same-calendar-day stations are weakly dependent (Wilson anti-conservative).

**Per-trial hold:** `held = 1` iff CLI **final** `tmax_f` (not superseded) ∈ **the rung bought**, not the day’s winner if different.

**Per-trial $ PnL:** `1{held} − fill_px − fee`, `fee = 0.06 · C · p · (1−p)` modelled, replaced by venue-observed fee when the fill carries one. Banker’s $0.01 (`fees.py:122-130`). Win for ROI: `sum(PnL) > 0` over the scored set.

**Break-even (hold-rate test):** `BE(ā) = ā + 0.06·ā·(1−ā)`, `ā = mean fill_px` of the stratum. Primary comparator stays this (kill amendment), not a new dollar CI.

**CI:** Wilson 95%, `z = 1.959963984540054` (`archive_correction_probe.py:66,352-363`). `k = Σ held`, `n = |scored taken fills|`.

| Call | n | Rule |
|---|---|---|
| UNDERPOWERED | n &lt; 60 | not dead, not alive |
| **KILL** | n ≥ **60** | Wilson **upper**(k/n) **&lt; BE(ā)** pooled, **or** any station / ask-band stratum with n≥60 and upper &lt; BE_s |
| **SURVIVE** | n ≥ **150** | Wilson **lower**(k/n) **&gt; BE(ā)** **and** no n≥60 stratum cell-dead **and** `sum(PnL) > 0`. Season-local (no DJF+SON pool). |
| Structural dead | — | every tape-visited cell is n/a / m=1 / open-lower, or live taken rate ≈ 0 over ≥15 afternoon-covered **listed** station-days (L-9: no seller) |

Live implements lag 15 only; paper still requires 10 **and** 15 for the family. Do not claim family SURVIVE until the **tape join** at lag 10 also survives on the same calendar (offline, no extra live orders).

**Clock at 3 taken / listed-day, ~9% venue skip:** taken/calendar-day = `3 × 0.91 = 2.73`. From first live-small listed day D0: **n=60 at D0+22 calendar days**, **n=150 at D0+55**. If D0 = 2026-09-04: **2026-09-26** and **2026-10-29**. (Memo 09-22 / 10-21 were zero-skip; missing-cohort: “about a week” later.) If taken stays at the 09-01 rate (~1/listed-day): n=60 ≈ **2026-11-09**, n=150 ≈ **2027-02-16**. Taken rate going forward is **UNVERIFIED**. Skip-days do not count as trials.

**Falsify the family for good:** KILL fires, or SURVIVE fails at n≥150, or the live book never offers the cell (taken≈0). Then stop this book class; do **not** add ΔT/month/forecast screens to resurrect it (kill-amendment; forecast family already dead). Recorder + offer-gate remain.

---

## 7. Package and gates

**New minimal package:** `src/breezy/strategy/current_rung_hold/` `{config,decision,strategy}.py`.

Do **not** host in `running_extreme_lock` (open-tail CLI-preliminary lock; interior `NotImplemented`; L-9 dead). Do **not** host in `forecast_*` (killed; no forecasts). Do **not** host in `cli_settlement_print_lock` (post-print, 0 asks, L-7/L-9). Copy **shape** from `running_extreme_lock` (observation signal, entry-only halt, `evaluate_order`, `SharedExposureMixin`) and **execution seam** from `cli_settlement_print_lock` (IOC limit BUY, `post_only=False`). Direct import; no `pyproject.toml` / `__init__.py` registration (`STRATEGY_QUICKSTART.md` §10). Subscribe **`OrderBookDepth10`**, not quote-only (§3.1 trap). Filter weather/obs with `WeatherBucketFacts.applies_to`.

Depends on **BL-24 Seam A+B landing first**. Strategy without live `R(t)` cannot implement the entry rule.

**Existing `evaluate_order` order** (`risk.py:505-667`): settlement_halt → too_close_to_settlement → future/stale signal → min_model_edge → shorts → missing ask → quote_tradable → exclusive_bucket_conflict → max_position / event / location / simultaneous → equity (buys) → ask depth.

| Rule | Existing vs new |
|---|---|
| `allow_short=False` | existing; leave False |
| halt 1.0 h / min 2.0 h | existing backstop; **entry-only in strategy** (new control flow, not a new limit value) |
| stale quote 15 min / future quote | existing |
| stale observation | existing **if** `stale_observation_hours=0.5` set |
| shorts / missing ask / depth&lt;1 | existing |
| exclusive one-YES / station-day | existing (does **not** encode “first snapshot only” — **new latch** in strategy) |
| position/notional/count/equity-fraction | existing; inert at 1 lot if equity observed |
| afternoon window, ASK lag 15, archive table, ask∈(0.05,0.95), m=0/open-upper, IOC-miss consumes day | **new, decision layer** |
| `observation_unavailable` | **new counted reason** (BL-24 A4); do not add a parallel branch in `evaluate_order` |
| `min_liquidity_contracts` | **config to 1.0** (default 25 blocks the measurement) |
| `min_model_edge` | **config to 0.0**; taken filter is `edge>0` with **venue** `venue_fee_prob`, not flat `transaction_cost_prob=0.015` (`costs.py`) |
| ask-only quote | **wiring**, not a new RiskLimits field |
| operator daily budget / max per position | **unset; do not assign** |

---

## 8. Top three self-fooling modes

1. **L-21: archive base rate vs forecast-conditioned ask.** MDW 09-01: `p_hold_lower=0.594` vs ask 0.06, “edge” +0.53, settled 93 above `[91,92]` — MM was right (`mb_current_rung_edge_2026-09-02.md` audit). Guard: archive **selects only**; kill/survive is **realized** `k/n` vs `BE(ā)`; freeze Part A; no post-hoc ΔT/month/forecast screen.

2. **Acting on R at t while lifting the ask the MM is cancelling (L-7/L-9).** Public ASOS is their information set; Breezy’s IEM poll is not faster. Guard: lag **15 min on the quote after receipt of the R-setting obs**; IOC at **displayed** ask, no chase; miss consumes the day; missing/stale ASOS refuses rather than carrying yesterday’s R.

3. **Pseudo-replication.** Three stations on one synoptic day are not three climate draws; 14k MDW snapshots are one day. Guard: one trial/station-day; no snapshot-weighted pool; stratum kill per station and ask-band at n≥60; report climate-days alongside n; skip-days excluded (not zeros).

**UNVERIFIED (do not silently assume):** IEM same-day latency vs public METAR; taken rate after 09-01 (1/4 covered); whether `currentBalance` includes position notional (T-4); per-market `minimumTradeQty` vs 1.0; tick `0.01` vs `0.005` (always `make_price`).
