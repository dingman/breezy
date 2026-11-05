# Kalshi integration plan — 2026-09-03

**Peer-reviewed 2026-09-03 (trading-bot-architect): ACCEPT-WITH-AMENDMENTS, 16 VERIFIED tags spot-checked, zero downgrades; five amendments applied (K-4 before K-3, K-4.5 provisioning, K-9 pacing + fill transport, `allow_short` scope).**

**Status: PLAN ONLY. Nothing here is implemented and nothing here may be implemented
before the §15 gate opens.** Kalshi.com is the committed second venue; Polymarket.us
is the first and is **not proven end-to-end yet**. No item below may delay, reorder,
or consume budget from the Polymarket.us path.

**Standing rules for this document**
- Every mechanic is marked **VERIFIED(source, date)**, **UNVERIFIED**, or **MISSING**.
  VERIFIED means a live read-only probe or a captured artifact in this repo — never a
  secondary doc, never a Polymarket.us analogy.
- Polymarket.us facts are **not** Kalshi facts. §16 lists the assumptions that must
  never be carried across. Every one of them is a live defect if copied.
- Nautilus Trader 1.231.0 has **ZERO Kalshi support**: zero doc hits, zero installed
  symbols, absent from `integrations/index.md`
  (VERIFIED: `docs/reference/nautilus/digests/prediction-markets-native-support.md`
  fact 28 / §Kalshi, 2026-08-22). So L-1's null hypothesis is REFUTED *for venue
  protocol only*; it stays live for every model, account, fee, settlement and
  lifecycle concern, where Nautilus does provide natives.
- Probe budget assumption throughout: Kalshi's public API answered ~4 req/s per IP,
  unauthenticated, with 429 as congestion not error
  (VERIFIED: `scripts/analysis/k1_kalshi_prior.py:876-937`, 2026-09-02).

---

## 1. Market discovery

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|1.1|Base URL `https://api.elections.kalshi.com/trade-api/v2`|**VERIFIED**|`scripts/analysis/k1_kalshi_prior.py:213`; 31,233 markets listed over 5 series, 2026-09-02|
|1.2|`GET /markets?series_ticker=&status=settled&limit=1000` + `GET /historical/markets?series_ticker=` with `cursor` pagination|**VERIFIED**|`k1_kalshi_prior.py:939-960`, 2026-09-02. Both families needed; dedupe by `ticker`|
|1.3|`GET /historical/cutoff` → 200 unauthenticated; cutoff 2026-07-04|**VERIFIED**|`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md:26,30`|
|1.4|`GET /series/{ticker}` metadata shape|**VERIFIED**|`tests/fixtures/kalshi/series_KXHIGHNY.json` (captured 2026-09-02: `fee_type`, `fee_multiplier`, `settlement_sources`, `category`, `frequency`)|
|1.5|Series **enumeration** (listing all weather series without knowing tickers)|**MISSING**|Only 5 tickers are known by name. Experiment: `GET /series?category=...` / `GET /events` paged, unauthenticated; assert `KXHIGH*` set ⊇ the five. **~200 GETs, <10 min, $0**|
|1.6|Live/open-market discovery cadence + `status` vocabulary (`open`/`closed`/`settled`/other)|**UNVERIFIED**|Only `settled` was ever requested. Experiment: one `GET /markets?series_ticker=KXHIGHNY&limit=100` per status value, tabulate. **~10 GETs, minutes, $0**|
|1.7|Rate-limit headers / documented tier for unauthenticated reads|**UNVERIFIED**|~4 req/s measured, **no `Retry-After`** (`k1_kalshi_prior.py:899-905`). Experiment: capture full response headers on 20 paced GETs. **20 GETs, minutes**|

## 2. Weather-market classification

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|2.1|Five daily-high series `KXHIGHNY`, `KXHIGHMIA`, `KXHIGHCHI`, `KXHIGHLAX`, `KXHIGHTSFO` (SF is **not** `KXHIGHSF`)|**VERIFIED**|`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md:42-43`|
|2.2|`series.category == "Climate and Weather"`, `frequency == "daily"` as the classification key|**VERIFIED (one series only)**|`tests/fixtures/kalshi/series_KXHIGHNY.json`. Experiment: fetch `/series/{t}` for the other four + 5 non-weather series; assert the discriminator separates them. **10 GETs, minutes**|
|2.3|Whether other weather variables exist (low temp, precip, wind) and their series grammar|**MISSING**|Breezy's variable is daily high only. Experiment: §1.5 enumeration + inspect titles. **folded into 1.5**|

## 3. Contract normalization onto Breezy's normalized fields

Target fields: platform, event id, market id, contract id, location, station,
variable, threshold/range, close time, resolution time, settlement rule.

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|3.1|`platform` = a new registry venue key `kalshi`; registry is already keyed `(venue, city)`|**VERIFIED (Breezy side)**|`docs/plans/WEATHER_INGESTION_PROPOSAL.md:100`; `docs/core/RUNBOOK_NWS_COLLECTION.md:32-36` — **no `kalshi:` entry exists yet**, so `kalshi:NYC` is currently a config error. Adding it is a §15 increment|
|3.2|Contract id = ticker grammar `SERIES-YYMMMDD-Bxx.x` (2-degree between-buckets) and `-Txx` (tails)|**VERIFIED**|`docs/evidence/…_2026-09-02.md:43-44`; parser `k1_kalshi_prior.py:412`|
|3.3|Event id (`event_ticker`) and its relation to market ticker|**UNVERIFIED**|Never read. Experiment: inspect one `/markets` row's `event_ticker` + `GET /events/{e}`. **3 GETs, minutes**|
|3.4|Location→station binding (NYC/MIA/**MDW not ORD**/LAX/SFO)|**VERIFIED**|`rules_primary` gave `CLINYC/CLIMIA/CLIMDW/CLILAX/CLISFO`, `docs/evidence/…_2026-09-02.md:15`. Breezy's own station table is `(venue, city)`-keyed and must be **re-derived per venue, never copied**|
|3.5|Threshold semantics: tail markets ("greater than 90") resolve on `floor_strike = 90` — an **off-by-one trap**|**UNVERIFIED (trap VERIFIED, rule not)**|`docs/evidence/k1_kalshi_prior_2026-09-02.md:34`. K1 deliberately used the venue `result` instead of re-deriving. Experiment: for 200 settled tails, compare `result` against `floor_strike`/`cap_strike` and the NWS CLI `tmax_f`; derive the `>` vs `≥` operator empirically. **~200 cached rows + NWS join, 1-2 h, $0**|
|3.6|Close time / open time: modern markets open **14:00Z on D-1**; `open_time` present and usable|**VERIFIED**|`docs/evidence/…_2026-09-02.md:16`; applied not assumed at `k1_kalshi_prior.py:509`, 2026-09-02|
|3.7|Resolution/expiration timestamps (`close_time`, `expiration_time`, `settlement_timer_seconds`)|**UNVERIFIED**|Not read by any Breezy code. Experiment: dump all timestamp fields from 20 settled + 20 open markets, compare against observed settlement instants. **40 GETs, ~1 h**|
|3.8|Settlement-rule text (`rules_primary`, `contract_terms_url`, "last fair price" clause)|**VERIFIED (text captured)**|`tests/fixtures/kalshi/series_KXHIGHNY.json` `product_metadata.important_info` — material-error hold, else *last fair price determined by Kalshi*. Interpretation for our resolver is **UNVERIFIED**|

## 4. Pricing and implied probability

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|4.1|Prices are cents in `[0.01, 0.99]`; 0.00/1.00 are settlement-only|**UNVERIFIED**|Asserted at `docs/specs/BACKTEST_VENUE_CONFIG.md:290` (§8 Kalshi portability) with no probe. Observed min 0.0100 / max 0.9900 across 30,323 markets is *consistent* (`docs/evidence/k1_kalshi_prior_2026-09-02.md:87,105`) but is a sample, not a bound. Experiment: read `tick_size`/min/max fields on `/markets` rows for all five series. **~20 GETs, minutes**|
|4.2|Implied probability = price directly (`qty × p = collateral`)|**VERIFIED (Nautilus side)**|`…/prediction-markets-native-support.md` fact 5 + capability table, 2026-08-22 — `BinaryOption.notional_value` is native, no adapter arithmetic. **Kalshi-side wire unit UNVERIFIED**|
|4.3|Wire units of `yes_ask`/`yes_bid` in candlesticks|**UNVERIFIED**|`k1_kalshi_prior.py:551` (`_candle_decimal`) normalizes; the raw unit was never pinned in a doc. Experiment: assert one raw payload's integer cents against a known 0.24 quote. **1 GET, minutes**|

## 5. Fee calculation

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|5.1|Functional form `theta * C * p * (1-p)` — same shape as Polymarket.us, so fee→0 at settlement survives|**VERIFIED**|`tests/fixtures/kalshi/series_KXHIGHNY.json` `"fee_type": "quadratic"`, `"fee_multiplier": 1` (2026-09-02); `docs/specs/BACKTEST_VENUE_CONFIG.md:287-289`|
|5.2|Taker coefficient **0.07**|**UNVERIFIED**|Used as K1's only differing input (`docs/evidence/k1_kalshi_prior_2026-09-02.md:9`) but sourced secondarily. Experiment: fetch Kalshi's published fee schedule and reconcile against `fee_multiplier`; confirm with one real fill at go-live. **1 fetch + 1 fill**|
|5.3|Maker coefficient **0.0175**|**UNVERIFIED — explicitly flagged**|`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md:62-63`; `BACKTEST_VENUE_CONFIG.md:288`. Breezy is taker-only by construction (`MakerRebateUnmodelledError`, `src/breezy/adapters/polymarket_us/errors.py:287`) — keep that refusal on Kalshi until a maker fill is observed|
|5.4|Rounding: Kalshi rounds **UP per trade**; Polymarket uses banker's rounding on the cumulative|**UNVERIFIED**|`BACKTEST_VENUE_CONFIG.md:288-289`, no probe. Experiment: compare charged fee against `ceil` and `round-half-even` on the first 20 real fills. **go-live only**|
|5.5|Settlement fee (whether the resolution leg carries a commission)|**MISSING**|Unknown on Kalshi; the analogous Polymarket.us question is open as OQ-9 (`docs/plans/EXEC_SPINE_2026-09-01.md:942-944`). Experiment: hold one contract to settlement, read the fee field. **go-live only**|

## 6. Order-book and bidding mechanics

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|6.1|**YES/NO share ONE book** — resting a NO bid *is* offering YES|**UNVERIFIED — highest-consequence item in this section**|`BACKTEST_VENUE_CONFIG.md:281-284`, asserted not probed. Getting it wrong **double-counts exposure**. Experiment: `GET /markets/{t}/orderbook` on one live market, cross-check `yes` and `no` ladders for the p↔1−p mirror. **2 GETs, <1 h**|
|6.2|Depth beyond top-of-book|**MISSING**|Candlesticks carry **no size at all** (VERIFIED: `docs/evidence/k1_kalshi_prior_2026-09-02.md:32`; `…_2026-09-02.md:59`). Experiment: sample `/markets/{t}/orderbook` every 60 s for one station-day; report levels/side and size distribution. **~1,400 GETs, 1 day wall-clock, $0**|
|6.3|Tick size|**UNVERIFIED**|Cent grid inferred from observed prices only (§4.1). Experiment: read `tick_size` per market. **folded into 4.1**|
|6.4|Min/max order size, notional minimum|**MISSING**|No Kalshi figure anywhere in this repo. Experiment: read `/markets` size fields; confirm at go-live by rejection. **~10 GETs**|
|6.5|Time-in-force vocabulary, partial fills, cancel/replace, market orders|**MISSING**|Zero evidence. Kalshi *may* supply a client order id, which Polymarket.us does not — that changes R-4/R-7 materially (`EXEC_SPINE_2026-09-01.md:972-977`, marked UNVERIFIED there too). Experiment: read the order-entry API reference, then confirm on a 1-contract live order. **docs read ~2 h; confirmation is go-live**|
|6.6|A real trade tape exists (Kalshi publishes trades)|**UNVERIFIED**|`BACKTEST_VENUE_CONFIG.md:291-292` — this is why `trade_execution=False` "expires" on Kalshi. Experiment: `GET /markets/trades` for one market. **2 GETs**|

## 7. Authentication and signing

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|7.1|Headers `KALSHI-ACCESS-KEY` / `-TIMESTAMP` / `-SIGNATURE`|**UNVERIFIED**|Repo claim only: `.claude/skills/polymarket-us-integration/SKILL.md:268-271`. No Kalshi request has ever been signed here|
|7.2|Canonical string `timestamp + METHOD + path`|**UNVERIFIED**|Same source. Polymarket.us needed a **live probe** to settle its own canonical form (`_probe_canonical_string`, `EXEC_SPINE_2026-09-01.md:34`) — assume Kalshi will too|
|7.3|Algorithm **RSA-PSS SHA256**, not Ed25519|**UNVERIFIED**|`SKILL.md:271`. Different salt lengths / failure surface. `src/breezy/adapters/polymarket_us/signing.py:1,158-185` is Ed25519-only|
|7.4|Sanctioned shared seam is `sign(bytes) -> bytes` **only**; canonical-string builders stay venue-specific|**VERIFIED (Breezy decision)**|`SKILL.md:273-275`; `docs/core/AGENT_ARCHITECTURE.md:163`. Do **not** unify the builders|
|7.5|All Kalshi reads to date were unauthenticated; 401/403 is a stop-and-report condition|**VERIFIED**|`k1_kalshi_prior.py:917-922`, 2026-09-02. **No Kalshi account or key exists**; creating one is a §15 gated step, never a probe side-effect|

## 8. Historical data availability

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|8.1|29,403 settled markets / 5,417 city-days, 2021→2026, five cities|**VERIFIED**|`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md:32-43`|
|8.2|Candlesticks with separate `yes_ask`/`yes_bid`/trade OHLC at 1/60/1440 min|**VERIFIED**|ibid. :20-22; paths `historical/markets/{t}/candlesticks` and `series/{s}/markets/{t}/candlesticks` (`k1_kalshi_prior.py:973-977`)|
|8.3|Settled `result` field is ground truth, directly|**VERIFIED**|`docs/evidence/k1_kalshi_prior_2026-09-02.md:34`, 30,323 members measured|
|8.4|Two regime breaks inside Kalshi's own history (2021-22 single-threshold vs 2023+ exhaustive buckets) — **must stratify**|**VERIFIED**|ibid. :54-67, :111|
|8.5|Whether the archive can be refreshed forward indefinitely (retention/cutoff drift)|**UNVERIFIED**|Cutoff 2026-07-04 was a point observation. Experiment: re-`GET /historical/cutoff` monthly. **1 GET/month**|

## 9. Strategy portability

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|9.1|The lock / cheap-D-1 family is **DEAD on Kalshi** in the 2023+ era at ask ≤0.03 and ≤0.05, per-station and pooled|**VERIFIED**|`docs/evidence/k1_kalshi_prior_2026-09-02.md:139-156,169-171` (n=30,323). Headline verdict is UNDERPOWERED overall; the FAMILY_DEAD cells are the binding read. It is also dead on Polymarket.us (`no-family-has-an-edge`, 2026-09-02) — **a Kalshi swap does not resurrect it**|
|9.2|Cost model is venue-neutral by injection — `theta` arrives via `FeeCoefficientSource`|**VERIFIED**|`src/breezy/strategy/weather_common/costs.py:67-74`: "the eventual move … a wiring change, not a strategy rewrite". Nothing there names a venue|
|9.3|Settlement **economics** carry over because settlement is keyed on the NWS observation, never a venue field|**VERIFIED (design)**|`EXEC_SPINE_2026-09-01.md:853-854,969`|
|9.4|Whether a *different* family has edge on Kalshi|**MISSING**|Kalshi history is a family prior only; it cannot estimate any venue's own ask distribution (`docs/evidence/k1_kalshi_prior_2026-09-02.md:5,250`). No family may be promoted on Kalshi history alone|
|9.5|Buckets within one station-day are **not independent** (exhaustive ladder ⇒ exactly one YES)|**VERIFIED**|ibid. :220-228. Any Kalshi-history study must use station-days, not markets, as the effective n|

## 10. Settlement and resolution sources

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|10.1|Kalshi settles on the **same NWS CLI product** as Breezy (`CLINYC/CLIMIA/CLIMDW/CLILAX/CLISFO`), read via The Weather Company — one hop more|**VERIFIED**|`docs/evidence/k1_kalshi_prior_2026-09-02.md:34`; `tests/fixtures/kalshi/series_KXHIGHNY.json` `settlement_sources` = The Weather Company / weather.com/kalshi|
|10.2|Material-error hold: expiration may be held to a revision or the Expiration Date; if no data, resolve to **last fair price determined by Kalshi**|**VERIFIED (text)**|fixture `product_metadata.important_info`, captured 2026-09-02. Numeric behaviour **UNVERIFIED**|
|10.3|Non-binary results occur (2 voids in 31,233)|**VERIFIED**|`docs/evidence/k1_kalshi_prior_2026-09-02.md:46` — a settlement price outside {0,1} is a **real** case on Kalshi, not theoretical. The `assert px ∈ {0,1}` rule at `BACKTEST_VENUE_CONFIG.md:206` must **raise**, never coerce|
|10.4|Settlement *timing* (Kalshi's instant vs Polymarket.us's 08:00 ET / 11:00 ET review window)|**MISSING**|Polymarket.us times are at `WEATHER_INGESTION_PROPOSAL.md:92` and are **venue-specific — do not carry over** (`:423`). Experiment: log `settlement_timer` fields + observe 20 settlements. **~1 week passive, $0**|
|10.5|Disagreement rule (NWS owns the OUTCOME, venue owns the CASH; divergence flagged, never overwritten)|**VERIFIED (design, portable)**|`EXEC_SPINE_2026-09-01.md:851-868`|

## 11. Position tracking

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|11.1|Kalshi permits **collateralized naked shorts**; Breezy's Polymarket.us no-naked-SELL guard becomes an *artificial constraint* there — silently suppressing trades rather than erroring. **Scope limit:** this changes only the *mechanical* over/under-locking check in the venue-specific order guard; `RiskLimits.allow_short` (`src/breezy/strategy/weather_common/risk.py:161`) stays `False` per the repo-wide invariant and is out of scope for K-9|**UNVERIFIED (asserted)**|`BACKTEST_VENUE_CONFIG.md:284-286`. The guard is `breezy.runtime.backtest_order_guard.BacktestOrderGuard` (`:110-121`). Experiment: read the Kalshi position/margin API reference; confirm at go-live. **~2 h docs**|
|11.2|One-book hazard: a YES long and a NO long are the **same** exposure, so naive per-`InstrumentId` netting double-counts|**UNVERIFIED**|Follows from 6.1; unresolved until 6.1 is probed. `OmsType.NETTING` transfers (`BACKTEST_VENUE_CONFIG.md:278-279`) but only once the instrument↔side mapping is right|
|11.3|Position-report semantics (dust thresholds, `expired` flags)|**MISSING**|The Polymarket.us analogues (sub-0.01-share omission) are venue facts, not universals (`…prediction-markets-native-support.md` trap 16)|

## 12. Execution adapter — native Nautilus extension points

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|12.1|`InstrumentProvider` is the sanctioned extension point; Breezy already subclasses it|**VERIFIED**|`src/breezy/adapters/polymarket_us/provider.py:1-41`; `concepts/adapters.md:38-45` five-component contract per digest fact 26|
|12.2|`LiveMarketDataClient` / `LiveExecutionClient` bases + `start/connect/disconnect/stop/reset/dispose` lifecycle|**VERIFIED**|digest fact 26 + capability table ("Adapter base classes + lifecycle — Yes"), 2026-08-22|
|12.3|`BinaryOption` (Cython), `AccountType.CASH`, `OmsType.NETTING`, linear PnL, zero margin all transfer|**VERIFIED**|digest facts 3-5, 31, 35-39; `BACKTEST_VENUE_CONFIG.md:278-279`. **Currency is USD, not `pUSD`** — pUSD is a Polygon artifact (fact 40)|
|12.4|Template = the existing Breezy Polymarket.us adapter shape (`credentials → signing → transport → http → parsing → provider → data → exec/`)|**VERIFIED**|`src/breezy/adapters/polymarket_us/*.py` (29 modules, incl. `exec/client.py`, `exec/endpoints.py`, `exec/refusals.py`)|
|12.5|Sign seam: reuse `sign(bytes)->bytes` only; **new** canonical builder, **new** signer class (RSA-PSS)|**VERIFIED (decision)**|`SKILL.md:273-275`; existing signer is Ed25519-bound with `PERMITTED_METHODS = {"GET"}` (`signing.py:84`) — that read-only floor must be reproduced venue-side, not inherited by import|
|12.6|Live settlement: Nautilus has **NO** live consumer of `InstrumentClose`|**VERIFIED**|digest capability table "Live settlement of binary positions — NO", 2026-08-22. Kalshi inherits the same gap; R-9's NWS-keyed approach is the answer (§10.5)|

## 13. Testing requirements

| # | Item | Status | Evidence / experiment |
|---|---|---|---|
|13.1|**The first Kalshi commit MUST extend the egress-firewall classifiers in the same commit.** `_EGRESS_PATH_PREFIXES = ("src/breezy/adapters/polymarket_us/exec/",)` and `_VENUE_NAME_RE = /polymarket/i` mean a `breezy/adapters/kalshi/exec/` module matches **C1, C3, C4, C5, E0 — none of them** and ships outside B4 and N2 with every barrier green|**VERIFIED**|`tests/unit/test_polymarket_us_readonly_guard.py:202-203,229-232`; `tests/unit/test_cage_rule_constants_are_pinned.py:152-158,207-213` — which already carries `polymarket\|kalshi` as its *widened* counter-example. `EXEC_SPINE_2026-09-01.md:978-987`|
|13.2|Contract tests: `parse_float=Decimal` on all money, settlement price ∈ {0,1} raises otherwise, fee-at-settlement = 0, no-naked-SELL semantics re-decided (§11.1)|**VERIFIED (rules exist)**|`EXEC_SPINE_2026-09-01.md:963,1003`; `BACKTEST_VENUE_CONFIG.md:206,208-215`|
|13.3|Fixtures: extend `tests/fixtures/kalshi/` (today exactly one file) with market list, candlestick, orderbook and settled-market samples|**VERIFIED (gap)**|`tests/fixtures/kalshi/series_KXHIGHNY.json` is the only fixture; `scripts/analysis/k1_kalshi_prior.py` the only code|
|13.4|No secrets: no key, signature, canonical string, header or body in any log, exception, artifact or fixture|**VERIFIED (rule)**|`EXEC_SPINE_2026-09-01.md:491-497`; reuse `redaction.py:70` `redact_headers` and `redact_url` patterns venue-side|
|13.5|Gate command unchanged: `scripts/ci/run_tests_no_egress.sh` green including the new classifiers' non-vacuity proofs|**VERIFIED (process)**|`CLAUDE.md` grok guardrail 3|

## 14. Platform-specific risks

| # | Risk | Status | Note |
|---|---|---|---|
|14.1|Geographic / account / eligibility restrictions, KYC, funding rails|**MISSING**|Nothing in this repo. Series prohibitions exist (`fixture.additional_prohibitions`: Source-Agency employees, MNPI holders) — **VERIFIED** and directly binding if we ever ingest NWS-privileged data. Experiment: read Kalshi's eligibility terms; **operator decision, not an engineering one**|
|14.2|Fee rounds **UP** per trade → every modelled edge optimistic by up to one rounding unit per fill|**UNVERIFIED**|§5.4. Pessimize in the cost model until measured|
|14.3|Candlesticks carry **no size** → no historical fillability evidence; matches the Polymarket.us finding that the bid side is ~0.3 contracts|**VERIFIED**|`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md:57-59`|
|14.4|Venue-keyed egress firewall (§13.1) — the sharpest swap hazard, "security condition H3 one venue over"|**VERIFIED**|`EXEC_SPINE_2026-09-01.md:978-987`|
|14.5|Two regime breaks + non-independent buckets make any naive Kalshi backtest overconfident|**VERIFIED**|§8.4, §9.5|

---

## 15. Ordered build sequence

> **GATE (hard, non-negotiable): no increment below starts until the Polymarket.us
> end-to-end path is proven — a real order submitted, filled, reconciled and settled
> with one realized-PnL row (`EXEC_SPINE_2026-09-01.md:145-147`).** Until then the
> only permitted Kalshi activity is **K-0**: unauthenticated read-only probing that
> costs no build time and touches no `src/`.

Each increment states its L-1 null-hypothesis check (with the `file:line` to open,
per L-11: a claimed *gap* carries the same burden as a claimed native) and one exit
criterion.

| Inc | Work | L-1 null-hypothesis check | Exit criterion |
|---|---|---|---|
|**K-0** (pre-gate, read-only)|Close §1.5-1.7, §2.2, §3.3, §3.7, §4.1-4.3, §6.1-6.6 by public-API probe; capture fixtures|n/a — no Nautilus surface touched|Every item moves off UNVERIFIED/MISSING or is restated with a named blocker. ~2,000 GETs, <1 day, $0|
|**K-1**|Registry: add `(kalshi, city)` entries + per-city CLI binding|Registry keying already exists — open `WEATHER_INGESTION_PROPOSAL.md:100`, `RUNBOOK_NWS_COLLECTION.md:32-36`. **Native present, no new mechanism**|`BREEZY_SITES=kalshi:NYC` validates; station binding asserted against a live CLI body-header regex|
|**K-2**|Symbology + instrument parsing → Cython `BinaryOption`, USD, per-market tick/size precision|Open `binary_option.pyx:102-147` — constructor is native; six fields hard-coded (digest fact 4). **Nothing to build but the parser**|Fixture-driven test builds every ticker grammar in §3.2 incl. tails, round-trips ids|
|**K-4**|**Firewall extension — lands with or before any `adapters/kalshi/` module**|Open `test_polymarket_us_readonly_guard.py:202-232` and `test_cage_rule_constants_are_pinned.py:152-213`. **No native; Breezy-owned**|A synthetic `src/breezy/adapters/kalshi/exec/x.py` is classified by C1/C3/C4/C5/E0 and fails B4/N2 exactly as its Polymarket.us twin does|
|**K-3**|`KalshiInstrumentProvider` + read-only HTTP transport (GET-only allowlist, redaction). **May not merge unless K-4 is already in, or lands in the same commit**|Open `provider.py:41` (`InstrumentProvider` native) and `signing.py:84`. **Refuted only for the venue protocol**|Provider loads all five series from fixtures and from live GETs; method-allowlist non-vacuity test green|
|**K-4.5** (operator-gated)|Kalshi account provisioning, eligibility/KYC, funding rail, API key issuance. **Operator decision — the only step in this table the build side cannot take.** No key or secret enters the repo; credentials load from `~/.config/breezy` like the Polymarket.us ones|n/a — no Nautilus surface; §7.5, §14.1|Authenticated `GET /portfolio/balance` returns 200 with a redacted-logged body; the read-only signer test proves no key/signature/canonical string reaches any log or exception|
|**K-5**|RSA-PSS signer behind the shared `sign(bytes)->bytes` seam; canonical builder **separate**|Open `signing.py:1,158-185` — Ed25519-specific. Check `cryptography` for RSA-PSS before writing any primitive|Signed GET accepted by the venue; no key/signature/canonical string in any log or exception (asserted by test)|
|**K-6**|`LiveDataClient`: quotes + orderbook + trade tape; custom `Data` types if needed|Open the digest capability table's "Adapter base classes + lifecycle — Yes" and Betfair `data_types.py` (fact 33). **Native; only the venue protocol is ours**|One station-day captured end-to-end into the catalog, gap-audited|
|**K-7**|Fee model: `ProbabilityPriceFeeModel`/`PolymarketFeeModel`-shaped, Kalshi coefficient, **round UP**|Open digest fact 42 — exponent-1 curve is native; **rounding direction is not**|Fee test pins round-up against a captured real fill; maker path still refuses|
|**K-8**|Backtest venue config for Kalshi (`BACKTEST_VENUE_CONFIG.md` §8 as the diff list)|Open `backtest/engine.pyx:5965-5978` + `backtest/config.py:179` — `settlement_prices` is native|Settlement-price completeness invariant green for a Kalshi run; voids raise (§10.3)|
|**K-9**|`LiveExecutionClient`: submit/cancel, durable intent latch, order guard, reconciliation|Open `EXEC_SPINE_2026-09-01.md:959-969` per-increment tags; re-decide R-4/R-7 if Kalshi supplies a client order id (§6.5)|One 1-contract live order: submit → fill → reconcile → settle → one realized-PnL row, under the operator budget ceiling; order-submit retry/backoff paced against the AUTHENTICATED rate limit, confirmed by header capture on go-live (§1.7 measured reads only); the fill confirmation names its transport (WebSocket vs REST, §6.5 MISSING today)|
|**K-10**|Settlement/resolution: NWS-keyed price + venue cash reconciliation + divergence rate|Open `EXEC_SPINE_2026-09-01.md:851-868` — the ownership split is already designed|Divergence rate reported; above threshold halts new positions via the existing control|

**Explicitly NOT built:** any venue-portability abstraction, interface, or indirection.
Seams are **labelled**, never generalized (`EXEC_SPINE_2026-09-01.md:159`;
`AGENT_ARCHITECTURE.md:163`). K-1 through K-10 add a second concrete adapter; they do
not add a venue framework.

---

## 16. Polymarket.us assumptions that MUST NOT be carried over

Each is a **live defect** if copied. The Polymarket.us source is cited; the Kalshi
status is UNVERIFIED or MISSING in every case.

1. **Two `InstrumentId`s / two books per market.** Kalshi is asserted to be one book, two sides (`BACKTEST_VENUE_CONFIG.md:281-284`). Copying doubles exposure. → §6.1, §11.2
2. **"Short YES is not a venue primitive."** True on the Polymarket CLOB (`BACKTEST_VENUE_CONFIG.md:92-101`); Kalshi is asserted to permit collateralized shorts, making the guard a silent trade suppressor. → §11.1 — but `allow_short=False` is a strategy-layer invariant, not a venue artifact; Kalshi's capability does not relax it.
3. **theta = 0.06 and banker's rounding on the cumulative.** Kalshi's constant differs and rounds **up per trade**. → §5.2, §5.4
4. **Weather taker rate 0.05 / 25% maker rebate** (digest fact 41) — a Polymarket.COM *category* schedule; not a Kalshi fact at all.
5. **`pUSD` collateral and Polygon/EIP-712 signing, `private_key`/`funder` credentials, on-chain allowances, MATCHED→MINED→CONFIRMED finality.** All Polygon artifacts (digest §Load-bearing and incompatible). Kalshi is a fiat DCM: USD, RSA-PSS, final at match.
6. **`condition_id-token_id` instrument-id grammar.** Kalshi's is `SERIES-YYMMMDD-Bxx.x`/`-Txx` (§3.2); the split-on-`-` parsers break outright.
7. **Ed25519 signing and `SigningVariant` canonical builders** (`signing.py:1,100-152`). RSA-PSS has a different failure surface; only `sign(bytes)->bytes` is shared (§7.4).
8. **No client order id** — the reason R-7's latch is the *sole* defence. Kalshi may supply one (`EXEC_SPINE_2026-09-01.md:972-977`); re-decide, do not inherit.
9. **Settlement at 08:00 ET with an 11:00 ET CLI/METAR review window** (`WEATHER_INGESTION_PROPOSAL.md:92`) — explicitly venue-specific at `:423`. → §10.4
10. **Venue resolution semantics (UMA / `outcomePrices` / `tokens[].winner`).** Kalshi resolves via The Weather Company off the same NWS CLI (§10.1) — same underlying, different mechanism, different error modes.
11. **`quote_quantity=True` market-BUY semantics, 1-unit marketable minimum, 5-share resting minimum** (digest facts 19-20, trap 11) — venue-specific numbers; a copied assumption multiplies order size by ~1/p. → §6.4
12. **The egress-firewall classifier set itself.** `polymarket_us`-keyed by construction; inheriting it silently exempts every Kalshi module. → §13.1
13. **"The bid side is empty" (median top-of-book 0.3 contracts)** — a Polymarket.us measurement. Kalshi depth is MISSING (§6.2); do not assume it is better or worse.
14. **`trade_execution=False`.** Correct today only because Breezy has no trade tape; Kalshi is asserted to publish one (`BACKTEST_VENUE_CONFIG.md:291-292`). → §6.6
15. **Registry entries.** `kalshi:` is not a valid site value today (`RUNBOOK_NWS_COLLECTION.md:35-36`); the station table must be re-derived per venue, never copied (§3.4).
