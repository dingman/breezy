# KALSHI_CRH_EXPANSION_PLAN_2026-09-04 — Rev 3

Status: Rev 2 + all ten coordinator-addendum items folded into the body (no addendum section remains), plus the S0 probe contradictions resolved in place from `docs/evidence/venue/kalshi/s0_2026-09-04/S0_FINDINGS_2026-09-04.md` (verbatim vendor quotes; fixtures `tests/fixtures/kalshi/*_2026-09-04.json`). Supersedes Rev 2. Companion artefacts, referenced not restated: `docs/specs/PREREG_v1_kalshi_current_rung_hold_DRAFT_2026-09-04.md`, `docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`, `docs/evidence/grok_prereg_v2_ratification_2026-09-04.md` §Final ruling.

## Goal

Reach a `current_rung_hold` verdict (KILL or SURVIVE) sooner by multiplying **station-days**, without touching the running Polymarket.us path.

**Kalshi is a SIBLING family** (strategy-lead ruling R1): own PREREG, own n, own D0; Kalshi rows are **never pooled** into the PM tally. Two dispositive reasons: (a) the same station-day on two venues is one **weather event** — pseudo-replication, not independent draws (`mb_current_rung_edge_2026-09-02.md:244`); (b) fee θ differs, so a pooled break-even belongs to neither venue. S0 **strengthens** (a): the two venues do not even share a settlement *source* — Kalshi settles on The Weather Company, PM on the NWS CLI final (§Venue mechanics, settlement).

**Consequence, plainly: Kalshi on the SAME four cities adds realized-PnL rows and ZERO independent hold-rate events.** The PM family's n is unchanged by everything here. Same-city fills on both venues are admissible in **each** family (ratification (2)).

**The only speed lever is NEW STATIONS.** PM lists 5 cities, 4 usable (NYC hourly-excluded); Kalshi lists 24 with open daily events → **19 candidates** (`KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md:12-40`). **Stage B on Polymarket.us is impossible** — there is no PM station expansion to buy.

Take rate: **observed ~0.25 taken trials/station-day** (09-01, 4 station-days) vs archive-implied ~0.75 (`mb_...:246`). **Every projection here uses 0.25**; the archive figure is named only to show these are the pessimistic branch.

**Shadow trials are not evidence (R2).** Unfilled Kalshi shadow candidates are a **diagnostic prefix only** — they measure take rate and selector reachability, feed neither kill nor survive, never enter a tally, and captured days are **never retroactively scored**.

Hard constraints: Polymarket.us stays first; no Kalshi item may pause, reorder or consume the live PM path; `allow_short=False`; Nautilus is immutable.

## Inventory (file:line)

**Kalshi code that exists — there is no adapter at all.**
- `scripts/analysis/k1_kalshi_prior.py` — public-API study (base URL `:213`; pagination `:939-960`; rate-limit read `:876-937`). Read-only, unauthenticated. Tests `tests/unit/test_k1_kalshi_prior.py`.
- Fixtures: `tests/fixtures/kalshi/series_KXHIGHNY.json` plus the **S0 set** (`market_KXHIGHLAX`, `orderbook_KXHIGHLAX-26SEP05-T80`, `series_KXHIGHLAX`, `event_KXHIGHLAX-26SEP05`, `trades_...`, `headers_markets.txt`, all `_2026-09-04`).
- Evidence: `docs/evidence/k1_kalshi_prior_2026-09-02.md`, `kalshi_history_as_k1_prior_2026-09-02.md`, `venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md`, `kalshi_station_cadence_2026-09-04.md` (+ raw `venue/kalshi/raw/cadence_2025-07/`, `cadence_2025-01/`), `kalshi_station_temp_cadence_2026-09-04.md`, `venue/kalshi/s0_2026-09-04/`.
- **Absent:** `src/breezy/adapters/kalshi/`, symbology, settlement mapping, fee module, auth, read seam, write seam. Vendor markdown now snapshotted under the S0 evidence dir; **no `docs/reference/kalshi/` snapshot yet**.
- `src/breezy/registry/sites.toml:71-75` — already `(venue, city)`-keyed; **no `[sites.kalshi.*]` table exists**.

**Strategy / guard surface the second venue must satisfy.**
- `config.py:76` `SUPPORTED_STATIONS`; `:16-29` NYC/KNYC excluded (hourly-only), `UnsupportedStationError` `:88-95`; `:85` `STALE_OBSERVATION_MINUTES=50`; **validation hook `config.py:239`** (the pattern a new config field must follow); `:226` per-instance `required_fee_coefficient`; `:261-264` `archive_table_pin == archive_table.CORPUS_SHA256` from **one imported module**.
- `decision.py:264` `Refuse("fee_schedule_mismatch")`; `:249-256` `_fee = theta*ask*(1-ask)` ROUND_HALF_EVEN; `:294` `P_HOLD_LOWER`; `:298` `break_even = ask + _fee(...)`.
- `archive_table.py:32-33` frozen `CORPUS_SHA256`/`STUDY_GIT_SHA`; `generate_current_rung_hold_archive_table.py:115-125,149-157`.
- `mb_current_rung_edge_study.py:20` corpus 2021-01-01..2025-12-31; `:30` n_min=90/cell; `:176` `FEE_THETA=0.06`; `:179-181` `break_even(ask)`; `:727-746` `build_realized_stratum` (`break_even(mean_ask)` at `:743`).
- `live_family_tally.py:174-176` `_PricedRow(entry_ask, held)` — **no fee field**; `:184,197,248` call `build_realized_stratum` unmodified; `:139-171` `assert_live_only`/`assert_paper_only`; `:229-301` verdict; `:257-262` SURVIVE conjunction.
- `trial_scorer.py:70-139` — no `venue` field; `fee` IS stored per trial (`:107,138`); `:187` `pnl = held - fill_px - fee`.
- Fee guard F1 `polymarket_us/parsing.py:264-332`; venue-neutral seam `weather_common/costs.py:113-147`; extension point `polymarket_us/fees.py:80 PolymarketUSFeeModel(FeeModel)` (Cython base, keyword-invoked — parameter NAMES load-bearing, `:70-79`; fee is **concave**, `:86-88`).
- Barriers: `_EGRESS_PATH_PREFIXES` (`test_execution_egress_firewall_guard.py:172`), E2 class-base rule `:188,777-791` (**static single-file AST walk over immediate `node.bases`**, `:782-791`); `is_venue_touching` (`test_polymarket_us_readonly_guard.py:303-327`), C1 `:305`, C2 `:307`, C3 host `:195-198,312`, C5 name `:204,314`, **C4 `SDK_ROOT_PACKAGE="polymarket_us"` consumed at `:172,318,581,587,880,1205`**, C6 `:322-326`; cage pins `test_cage_rule_constants_are_pinned.py:152,209,895-898`.
- Permit `runtime/order_enablement.py:44` header, `:48` imports `polymarket_us.write_transport`, **class at `:148`**, `:169-219` `issue` (`:203` the ONE `WRITE_CANONICAL_STRING_VERIFIED`, now **`True`** — `write_transport.py:46-52`; `:209-210` the two operator caps). Minted once at `app/trade.py:178-190`.
- Ledger `src/breezy/adapters/polymarket_us/operator_controls.py:250-262` `DailySpendLedger` — **"State is process-local and in-memory … two processes do not share a ledger"**; `:274-285` one `threading.Lock`.
- Wiring precedent: `trade_cli.py:362-365`; `factories.py:545,640`.

## Null-hypothesis (Nautilus first)

Nautilus 1.231.0 has **zero Kalshi venue protocol** (`docs/reference/nautilus/digests/prediction-markets-native-support.md` fact 28) — refuted for protocol only. Everything else stays native: `BinaryOption`, `AccountType.CASH`, `OmsType.NETTING`, `InstrumentProvider`, `LiveMarketDataClient`/`LiveExecutionClient` + lifecycle, `LiveExecutionEngine` reconciliation, **`FeeModel`**, `add_*_client_factory`. Known native gap transferring unchanged: no live consumer of `InstrumentClose` (`EXEC_SPINE_2026-09-01.md:851-868`).

## Venue mechanics (S0-VERIFIED; supersedes every contrary §-number in `KALSHI_INTEGRATION_PLAN_2026-09-03.md`)

**Market shape (§6.1) — there is NO NO-ticker.** `order_direction.md`: "**`bid ≡ yes`, `ask ≡ no`**, always"; create-order-v2 `BookSide`: "For event markets, this refers to the **YES leg only**: `bid` means buy YES, `ask` means sell YES." The orderbook returns yes bids and no bids only, "a bid for yes at price X is equivalent to an ask for no at 1-X". **One ticker, one signed position.** Rev 2's F5 exit ("two DISTINCT instrument ids … NETTING never nets across them") rested on a false premise and is **deleted**.

**F5 (rewritten), the testable exit:** **exactly ONE `BinaryOption` per market ticker**, constructed the way Polymarket's BL-6 constructs its single instrument; the bot is **BUY-YES-only → `side="bid"` always**; a NO-side instrument is never created, so nothing can net against it. Fixture proof from `market_KXHIGHLAX_2026-09-04.json`: `yes_ask_dollars 0.4100 = 1 − no_bid_dollars 0.5900`, `no_ask_dollars 0.6000 = 1 − yes_bid_dollars 0.4000` — the identity that shows the NO quotes are the same book, not a second instrument. A test asserting a NO instrument exists is now a **defect** and must not be written.

**Prices/precision (§4.1/§4.3/§6.3).** Prices are **fixed-point dollar STRINGS** (`yes_ask_dollars:"0.4100"`); FixedPointDollars: "Most request fields accept 2-4 decimal places … responses emit up to 6". **Integer-cent fields (`yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `notional_value`, `response_price_units`) were REMOVED 2026-01-15** — symbology, parsing, and quote normalisation **never handle cents**, and any "raw integer cents" path is a defect. **No `[0.01,0.99]` bound is published**; the declared grid is `price_ranges:[{start "0.0000", end "1.0000", step "0.0100"}]` with `price_level_structure:"linear_cent"`. **`tick_size` is DEPRECATED (since 2026-01-05, removal 2026-05-07) → never read it**; price precision comes from `price_level_structure` + `price_ranges[].step` **per market** (tapered `center_{c}_edge_{e}_cent` and sub-cent shorthands `whole`/…/`centi`=$0.0001 exist). Quantity: `FixedPointCount`, "the minimum granularity is **0.01 contracts**" — fractional contracts are legal; **Breezy stays at `order_quantity=1`**, so precision is a constructor argument, never a sizing change.

**Status vocabulary (§1.6).** Lifecycle states are `initialized|active|inactive|closed|determined|disputed|amended|finalized`; the filter map is `unopened→initialized`, **`open→active`**, `paused→inactive`, `settled→finalized`. Fixture status = `"active"`. Any code or test comparing to `"open"` is wrong.

**Rate limits (§1.7).** "Every **authenticated** request costs tokens"; "**429 responses do not currently include `Retry-After` or `X-RateLimit-*` headers. There is no penalty or cooldown.**" Live 200 carried no rate-limit header. No documented unauthenticated tier exists → **the transport backoff is pinned in-repo, not inferred from headers**: fixed exponential backoff with jitter (base 1 s, cap 30 s, bounded retries) on 429, plus a client-side ≤4 rps cap for unauth reads, as a pinned constant with its own test. Never read `Retry-After`.

**Order entry (§6.5).** Endpoint is **`POST /portfolio/events/orders`** — "the legacy `/portfolio/orders` endpoint will be deprecated no earlier than May 6, 2026". Required body: `ticker, side, count, price, time_in_force, self_trade_prevention_type`. **No `action`/`type` fields in V2**; `side` is the `BookSide` enum `bid|ask`, **not `yes`/`no`**. **`time_in_force ∈ {fill_or_kill, good_till_canceled, immediate_or_cancel}` — IOC EXISTS**; "`GTT` is an internal execution type and is not a valid API value"; `expiration_time` is an **optional Unix timestamp in SECONDS** (not `expiration_ts`), **incompatible with IOC** ("cannot be combined"). Partial fills: response carries `fill_count`, `remaining_count` ("for IOC orders … the final state after unfilled contracts are canceled"), `average_fill_price`, `average_fee_paid`, `ts_ms`. **`self_trade_prevention_type` is REQUIRED**, enum `taker_at_cross|maker` → Breezy pins **`taker_at_cross`**: it sacrifices *our own* incoming taker order rather than removing a resting order, and Breezy holds no resting orders, so it is the conservative choice. *(The enum semantics beyond the two names are UNVERIFIED in the vendor text; the pin is recorded as pessimistic-by-choice and re-checked on the first fill.)* Cancel `DELETE /portfolio/events/orders/{order_id}` (returns `{order_id, client_order_id, reduced_by}`); batch `…/batched`; **cancel-all `DELETE /portfolio/events/orders`** ("newly placed orders may also be cancelled during the minute after the request"); open orders `GET /portfolio/orders?status=resting`; fills `GET /portfolio/fills`. **The Kalshi OP-SEQ positive control maps exactly onto these four** (it rests a GTC order by necessity — an IOC cannot rest — so the positive control exercises rest/read/cancel, not the IOC trading TIF; the first IOC is exercised by the first live shadow-to-live fill under S14): rest (GTC `bid` far from touch) → confirm via `?status=resting` → cancel by id → confirm absent, with cancel-all as the sweep, mirroring `OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md`. Bot-driven, never a UI step.

**R-7 durable latch, re-decided around `client_order_id` (VERIFIED to exist: request field, echoed on response and on cancel).** Decision: **the latch key becomes the `client_order_id`**, derived deterministically from the trial id (`kalshi:current_rung_hold/trial/{station}/{climate_day}`), so the local durable record and the venue-side identifier are the same string and a crash cannot orphan the mapping. **The venue's behaviour on a duplicate `client_order_id` is UNVERIFIED — the vendor text is silent on whether a repeat id is rejected, deduplicated, or accepted as a second order.** Therefore the latch is **NOT** relaxed into "the venue will refuse a duplicate": after any ambiguous submit the client **reconciles first** (`GET /portfolio/orders?status=resting` + `GET /portfolio/fills`, matched on `client_order_id`) and only re-submits when both reads prove absence. If a later probe shows the venue does reject duplicates, that is a second belt, never the first.

**Tail strikes (§3.5).** Strike is **EXCLUSIVE**: `strike_type:"greater"`, `floor_strike:80`, "greater than 80°", `yes_sub_title:"81° or above"`; `"less"`/`cap_strike:73` → "72° or below"; `"between"` floor 79/cap 80 is **inclusive both ends**. Relationships are read from `series_ticker`/`event_ticker` fields — terms.md: "**do not parse ticker strings to infer relationships**."

**Close/expiration (§3.7).** `close_time`, `open_time`, `expected_expiration_time`, `latest_expiration_time`, `settlement_timer_seconds:300`, `can_close_early`, `early_close_condition`. **`expiration_time` is a "Deprecated legacy field"** — prefer `latest_expiration_time`, or `expected_expiration_time` for the forecast. Rev 2 named the deprecated field; corrected here.

**Settlement (§10.4) — CONTRADICTS the "one NWS CLI event" premise.** `rules_primary`: "the maximum temperature recorded at Los Angeles (CLILAX) … according to **The Weather Company**"; `settlement_sources:[{"name":"The Weather Company","url":"https://weather.com/kalshi"}]` (carried on the **series** and **event** objects, not the market object; the market carries `rules_primary`); `rules_secondary`: "the official and final value … as reported by the Weather Company." **CLI is the station identifier only; TWC is the settlement source.** Schedule verbatim: "Expiration will occur on the sooner of the first **7:00 or 8:00 AM ET** following the release of the data … or **one week** after"; then a 300 s dispute timer at `determined`.

**Registry settlement-clock values for `[sites.kalshi.*]`** — `sites.py:62-68 _REQUIRED_SETTLEMENT_DEADLINE_FIELDS` requires five fields; S4 was BLOCKED on them and **resumes on these stated values**:
- `settlement_time_local = "08:00"` — the **later** of the two published ET instants; nothing in Breezy acts before the deadline, so the late bound is the safe one (that 07:00 may fire earlier is recorded, not modelled).
- `settlement_timezone = "America/New_York"` — VERIFIED ("AM **ET**"), and it matches the existing venue-clock discipline in `sites.toml:128-137`.
- `no_data_fallback_days = 7` — VERIFIED from "or one week after".
- `settlement_delay_time_local = "11:00"` / `settlement_delay_timezone = "America/New_York"` — **NWS-product-derived, not venue-derived (convergence edit).** This pair drives only the CLI review-extension window (`src/breezy/ingest/gaps.py:419-441,1044-1050`; `nws_actor.py:1696-1697`), i.e. when a climate day becomes EXPECTED; it is a property of the NWS CLI product and is therefore identical to the Polymarket entries (`sites.toml:136`). Pinning it at 08:00 would collapse the 08:00–11:00 review window and create false-positive gaps (`gaps.py:59-63`) — aggressive, not conservative. Kalshi publishes no analogue; the 300 s `determined` dispute timer is a different thing and is measured in S15.

**Eligibility/KYC (§14.1): UNVERIFIED and operator-only.** `docs.kalshi.com` carries no eligibility/jurisdiction/KYC text and `kalshi.com/regulatory/*` returns HTTP 429 to every non-browser UA. The only quotable constraint is the series' `additional_prohibitions` (source-agency employees; material non-public information). This is an operator decision, not a build item.

## Stations

**The four current cities are shared, not additive** — Kalshi lists NYC/MIA/**MDW (not ORD)**/LAX/SFO, the same five as PM. The value is the 19 candidates.

**Cadence rule, PINNED by the strategy lead**: **median-of-daily-medians ≤5 min AND ≥90% of days with daily median ≤5 min** (`kalshi_station_cadence_2026-09-04.md:9`). The ≥95% figure in Rev 2's header and S8 row is **superseded and deleted**; KHOU's July 83.3% fails both figures, so nothing is loosened.

**Measured, two sample months (2025-07 + 2025-01, all 21 stations, 12:00–17:00 local, IEM ASOS):** every candidate resolves to its ICAO **from the CLI product's AFOS headline, name-matched against `api.weather.gov/stations/K<loc>` — never geography**, and all 19 show 5.0-min medians; KLAX PASS / KNYC FAIL as designed controls. KHOU 2025-10: 100%; its July 83.3% and KATL's 96.7% were MADIS archive outages.

**Temperature-bearing cadence is the real gate** (`kalshi_station_temp_cadence_2026-09-04.md`): in `data=tmpf` pulls the 5-minute rows carry `tmpf=M`, so the cadence files establish 5-minute **observation-record** cadence, not **temperature** cadence. **18 of 19 carry 5-minute temperature on BOTH feeds** (live `api.weather.gov/stations/{icao}/observations`, archive IEM METAR T-group).
- **ADMITTABLE on gate item 1 (18):** KATL, KAUS, KBOS, KDFW, KLAS, KSDF, KMSP, KMSY, KEWR, KOKC, KPHL, KPHX, KSAT, KSAN, KSEA, KTTN, KDCA, KHOU*.
- **KDEN — HELD.** Archive clean; the **live** NWS feed published 6 observations on 2026-09-03 (60-min median). Recheck on ≥2 further days before admission or exclusion.
- **KHOU — HELD.** Live 5-min clean, but the **archive** loses 5-min rows from mid-2025-07 (hourly-only after); its usable 2021–2025 corpus density must be sized in S9 before admission.
- Precision asymmetry stands: archive T-group is tenths °C, live 5-min rows integer °C → the interval-valued accumulator remains required.

**Per-station settlement reconciliation is now the load-bearing admission test (R4, strengthened).** Because Kalshi settles on **TWC** while naming the CLI station, the PM four-station divergence rate is **not inherited and is UNMEASURED for Kalshi**. Gate: **n≥90 settled HIGH events per station**, agreement = venue `result` equals the **CLI-FINAL** winner via `WeatherBucketFacts.contains`, **Wilson lower (z=1.959963984540054) > 0.99**, voids counted separately and **raise**. Station identity is taken from `rules_primary` only, never `settlement_sources` or geography.

**Registry hazards carried into `[sites.kalshi.<CITY>]`** (all live-verified against api.weather.gov per `sites.toml:94-104`):
- **CLIHOU is Houston HOBBY (KHOU), not Bush/KIAH** — the second MDW-not-ORD trap.
- **CLIMSP's header reads "TWIN CITIES MN"**; **CLIAUS's reads "AUSTIN BERGSTROM"** — a city-name `body_header_regex` never matches.
- **Same-office collisions needing a NARROW regex:** **KOKX** issues CLIEWR + CLINYC; **KPHI** issues CLIPHL + CLITTN; **KEWX** issues CLIAUS + CLISAT. The sibling-decoy rejection test (`sites.toml:94-104`) is mandatory for all six entries.
- Three title/rules drifts pinned by a symbology test: `KXHIGHTSDF` title "SATX" vs rules Louisville/CLISDF; `KXLOWTMIN` "Minnesota" vs CLIMSP; `KXLOWTSDF` "SDX". **Rules are authoritative.**

**Archive cells (R3).** Each admitted station needs **its own `P_HOLD_LOWER` cells at n_min=90** from 2021–2025: extend `DENSE_STATIONS`, re-pull (IEM ASOS + NWS CLI finals, complete-24h days), regenerate. A thin cell reports `n/a` and `decision.py:294-296` refuses `p_hold_undefined` — correct behaviour, never a widened floor.

**Corpus-study parser defect (S9 scope).** `scripts/analysis/settlement_alignment_study.py::parse_metar_t_group` requires the 8-digit `Txxxxxxxx` form and drops the temperature-only 4-digit form (`RMK T0300 MADISHF`) as `missing_metar_t_group_row`. Measured rows/day effect: KBOS 7.1→59.4, KEWR 49.4→65.7, KDEN 62.6→64.1, KLAS 63.6→65.6, KSEA 63.0→64.4. The rev2 corpus must fix it RED-first (both forms, sign handling, a fixture from the KBOS raw) and re-measure density for **all** stations including the four live ones — **reported, never applied to v1**.

**Corpus pin versioning — a new corpus is a NEW pinned table, never an edit.** Emit `archive_table_rev2.py` with its own `CORPUS_SHA256`/`STUDY_GIT_SHA`; `archive_table.py` stays byte-identical so booked trials remain reproducible. This requires the pin's **source module to become selectable per config instance** — `config.py:261-264` hard-requires equality with one imported module, so "old pin untouched" cannot validate until that indirection lands (S9 exit). Pooling across pins is forbidden — stratify or refuse.

## Fees

- **`P_HOLD_LOWER` is venue-neutral** (climate only). **A Kalshi θ does NOT require regenerating the archive table** — only new *stations* do. Decision-time break-even IS venue-specific (`decision.py:298`, gated by `:264`).
- **θ is UNVERIFIED and stays UNVERIFIED for now.** The series object gives the fee **model** — `fee_type:"quadratic"`, `fee_multiplier:1`, uniform across all 102 daily series — confirming the functional form `_fee = θ·ask·(1−ask)` targets, but **not the coefficient**. A grep for `0.07`/"trading fee" over the entire 531 KB `llms-full.txt` returns nothing; the coefficient lives only in the fee-schedule **PDF on `kalshi.com`, which returns HTTP 429 to every non-browser agent**. Third-party blogs asserting 0.07 are **not admissible**. Two admissible closures: (a) the operator fetches the PDF in a browser and drops it under `docs/evidence/venue/kalshi/`; (b) **derive θ from the first real fill's `average_fee_paid`** against the known `count`/`price`. Until one lands, `required_fee_coefficient=Decimal("0.07")` is a **placeholder and Kalshi runs SHADOW**.
- **Rounding — Rev 2's "rounds UP per trade" is WRONG and is deleted.** `fee_rounding.md`, verbatim: "**Trade fee** | Fee from the fee model, rounded up to the nearest `$0.000001`", then "1. Compute `trade_fee = ceil_6dp(model_fee)` 2. `aligned_change = floor_precision(revenue - trade_fee)` 3. `rounding_fee = (revenue - trade_fee) - aligned_change`", plus "**The fee accumulator is maintained per order across all fills**", with net fee = trade fee + rounding fee − rebate. **`KalshiFeeModel(FeeModel)`** (the native extension point, mirroring `fees.py:80` including its keyword-invocation signature discipline `:70-79`) implements **exactly this**: `ceil_6dp` on the model fee, a **per-ORDER accumulator** carrying rounding fees and rebates across fills.
- **Config: the Rev 2 `fee_rounding ∈ {"half_even","up"}` field is REPLACED by `fee_rounding_rule`**, which *names a documented rule* rather than a rounding direction: `{"half_even", "kalshi_ceil6dp_order_accumulator"}`, validated at `config.py:239` exactly as the other frozen-for-life fields are, defaulting `"half_even"` (v1 behaviour byte-unchanged); Kalshi pins the Kalshi rule. Build-side constant, never an operator knob. `"up"` is not a legal value — it describes a rule the venue does not have.
- **Settlement-leg fee: VERIFIED ZERO for this product.** market_settlement.md: "**Settlement fees are zero for simple yes/no determinations** but may apply for sub-cent scalar settlement. The actual payout (`CollateralAmountChange`) is rounded to whole cents." KXHIGH*/KXLOWT* markets are `market_type:"binary"` with a yes/no `result` → zero. `trial_scorer.py:187`'s zero-settlement-leg assumption therefore **holds** for Kalshi binaries; **one measured settlement confirms it in practice** before any Kalshi row enters a verdict (S15). If a series ever changes `market_type`, this clause is void.
- **F1 must not be weakened.** `src/breezy/adapters/kalshi/parsing.py` gets its **own** `assert_fee_schedule_known` — same fail-closed-on-absence semantics as `polymarket_us/parsing.py:299-332`, **not an import** (an import lets one venue's marker unlock the other's fee path). Then widen the F1 *scanner* so any module under `src/breezy/adapters/kalshi/` reading `maker_fee`/`taker_fee` without the Kalshi guard fails. Widening coverage is a strengthening; relaxing a predicate is not permitted.
- Maker path keeps refusing (`MakerRebateUnmodelledError`) — Breezy is taker-only.

## Tally

**v1 is byte-unmodified while it is live** (ratification (1)(e), (3)). Rev 2's "convex … permissive" sentence was **wrong**: θ·a(1−a) is **concave**, so `break_even(mean_ask) ≥ mean(BE_i)` — the module-constant form is the *conservative* one and per-trial BE **lowers** the hurdle. Consequently per-trial BE is **not** a defect fix applied to v1; it is a v2/Kalshi-only registered design.

**Implementation is specified in `docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` and is NOT restated here.** It supplies S2 and S3 in full: the pure `settlement/current_rung_hold_v2.py` math (`BE_i = entry_ask_i + fee_i`, `π = mean(BE_i)`, `StratumV2`, Wilson-score `Z_k`, `look_verdict`), the boundary-table loader, the family manifest (venue + trial-id prefix + D0 as the family discriminant — **no `FilledTrial`/`ScoredTrial` schema change**), `scripts/analysis/family_tally_v2.py`, and the v1 non-modification pin. This plan's obligations against it: **no pooled path, no pooled flag, no combined line**; a `venue:` stratum so `cell_dead` can fire on Kalshi alone; `assert_family_only` refusing a PM row in a Kalshi tally and vice versa; and the Kalshi latch choosing its own trial-id prefix (`kalshi:current_rung_hold/trial/…`) without touching v1's.

## Execution & safety

**S1' — firewall/cage coverage is Polymarket-shaped and must be widened BEFORE any `src/breezy/adapters/kalshi/` file exists.**
- `_EGRESS_PATH_PREFIXES` (`:172`) is PM-only → add `src/breezy/adapters/kalshi/exec/`.
- `is_venue_touching` needs Kalshi equivalents for **path (C1)**, **host (C3 — `api.elections.kalshi.com`)**, **SDK root package (C4)** and **name (C5)**; the C4 equivalent must land at **all six** consumption sites (`:172,318,581,587,880,1205`).
- **E2 is a static single-file AST walk over immediate `node.bases` (`:782-791`); "full MRO" is not implementable without imports.** Restate as a **repo-wide transitive base-name closure** over class definitions, so a Kalshi client subclassing a Breezy intermediate that subclasses `LiveExecutionClient` is still classified.
- **Non-vacuity must include** (a) a synthetic module with a **NON-listed basename** and (b) a module whose only signal is **Kalshi's own SDK import**. Both must fail B4/B6 exactly as their PM twins do.

**S2' — `OrderSubmissionPermit` is venue-blind and must become per-venue (highest-severity finding).** Today `order_enablement.py:48` imports **Polymarket's** `write_transport`, `:203` checks the single `WRITE_CANONICAL_STRING_VERIFIED` (**now `True`**), and one permit is minted at `app/trade.py:178-190` — so the moment a Kalshi exec client exists it inherits PM's verified state and PM's operator enablement. Required: split into `PolymarketOrderSubmissionPermit` / `KalshiOrderSubmissionPermit`, each gated on **its own** verified-canonical-string flag and **its own** `orders_enabled_requested` flag; each submit path asserts its own permit **type** (`TypeError`, not truthiness); contract test both directions, plus "Kalshi cannot mint on PM's `True`".

**S4' — the shared `DailySpendLedger` is process-local.** The two operator caps are single values the repo never assigns; a per-venue ledger would silently double real daily spend against one unchanged number. Required: **both exec clients on the SAME `TradingNode`/process, sharing one ledger object**; an **identity** (not equality) contract test mirroring `ingest/shared_state.py:516-529`'s `ForeignComponentError` discipline; an explicit deploy statement that **a second systemd unit running Kalshi execution is a defect, not a deployment option**; and a non-interleaving proof (authorize-then-book synchronous, no `await` between check and book, so the `threading.Lock` at `:279` suffices) plus a two-submission race test.

**S3' — RSA-PSS auth is a named gate at S12, with three traps now VERIFIED as tests.**
1. **Algorithm:** `padding.PSS(mgf=MGF1(SHA256), salt_length=PSS.DIGEST_LENGTH)`, `SHA256`, **base64** output — **salt length 32**. Not Ed25519; `signing.py` is reusable only as `sign(bytes)->bytes`.
2. **Timestamp is MILLISECONDS** (`KALSHI-ACCESS-TIMESTAMP` "the request timestamp in **ms**"), alongside `KALSHI-ACCESS-KEY` (Key ID) and `KALSHI-ACCESS-SIGNATURE`.
3. **Canonical string = `timestamp + METHOD + path`, where the path INCLUDES `/trade-api/v2` and has the query string STRIPPED** ("sign only `/trade-api/v2/portfolio/orders` — strip the `?` and everything after it").
Each of the three is its own RED-first test (a seconds timestamp, a path missing the `/trade-api/v2` prefix, and a path retaining `?…` must each fail). Plus: leak tests over **multi-line PEM material** (`redaction.py:70-99` masks exact substrings only, so a PEM's interior lines pass through unmasked); **fail-closed key loading** mirroring `signing.py:158-185`; the **runbook §6 shell-only rule** carried verbatim for the Kalshi key. No key, signature, canonical string, header or body in any log, exception or fixture.

Other shape: a second `LiveExecutionClient` + factory via `add_exec_client_factory` — native. Kalshi analogues **duplicated, not shared**: GET-only method allowlist, its own `WRITE_CANONICAL_STRING_VERIFIED` (starts `False`; flips only on a live-probed canonical string, guarded by the AST no-monkeypatch scan at `test_polymarket_us_submit_order_chain.py:470-506`), redaction, refusal surface, submit chain, durable latch.

## Build order

**Sequencing: READ path + station qualification + archive cells + Kalshi SHADOW come FIRST; the write path (S12–S15) is gated on the take rate measured in shadow.** Each step is one commit, RED-first, gate `scripts/ci/run_tests_no_egress.sh`. **Never touched:** anything under `src/breezy/adapters/polymarket_us/`, the running strategy's config values, `deploy/systemd/breezy-quote-tape*`, the live `orders_enabled` permit path, `archive_table.py`, `live_family_tally.py`, `mb_current_rung_edge_study.py`.

| # | Work | Null-hypothesis check (open first) | Exit |
|---|---|---|---|
|**S0**|K-0 probes — **CLOSED 2026-09-04**; §Venue mechanics carries the verdicts, fixtures committed|n/a, no `src/` touched|Every item VERIFIED or carrying a named blocker (θ, min notional, eligibility, duplicate-`client_order_id`)|
|**S1**|**Firewall/cage widening first (S1')** — path/host/SDK(×6 sites)/name equivalents; E2 → transitive base-name closure; both non-vacuity modules|`test_execution_egress_firewall_guard.py:172,188,777-791`; `test_polymarket_us_readonly_guard.py:172,195-204,303-327,581,587,880,1205`|Both synthetic modules fail B4/B6/E2 exactly as their PM twins|
|**S2**|**v2/Kalshi tally path per the blueprint** — pure math, boundary loader, family manifest, v1 non-modification pin **first**|blueprint §Files; ruling (1)(a)-(e),(3)|v1 source-hash pin green (both directions, two neighbour mutants); non-vacuous BE golden `mean(BE_i) < break_even(mean_ask)`|
|**S3**|`family_tally_v2.py` barrier + strata (`pooled|station|ask|venue`)|blueprint §Data flow|A PM row cannot enter a Kalshi tally or vice versa; v1 output unchanged|
|**S4**|Registry `[sites.kalshi.{LAX,MDW,MIA,SFO}]` incl. the five settlement-clock fields (08:00 / America/New_York / 08:00 / America/New_York / 7), delay pair commented venue-unconfirmed|`sites.toml:71-75,94-104`; `sites.py:62-68`|`BREEZY_SITES=kalshi:LAX` validates; body-header regex asserted against a live product; **a Kalshi registry entry is NOT an ingest site** — the running NWS ingest unit never polls `kalshi:<city>` alongside `polymarket_us:<city>` (a second `NwsIngestActor` on one CLI product doubles NWS request rate under one `CrossSite403Window`, `shared_state.py:429-432,594-611`); shared stations reuse the PM actor|
|**S5**|Symbology + `KalshiInstrumentProvider` + read-only GET-only transport + pinned 429 backoff + redaction|`provider.py:1-41`; `binary_option.pyx` ctor|**ONE instrument per ticker** (F5 rewritten); precision from `price_level_structure`/`price_ranges[].step`; **no `tick_size` read anywhere**; no cent-field path; `active`-not-`open`; ticker grammar round-trips; three title/rules drifts pinned|
|**S6**|`KalshiFeeModel(FeeModel)` implementing `ceil_6dp` + per-order accumulator; own `assert_fee_schedule_known`; `fee_rounding_rule`; F1 scanner widened to the kalshi tree|`fees.py:70-80,86-88`; `parsing.py:264-332`; `costs.py:113-147`|Accumulator reproduces the documented 3-step arithmetic on a fixture; unresolved schedule refuses; scanner fails a guard-less reader|
|**S7**|`KalshiLiveDataClient` (quotes + book + trade tape) via `add_data_client_factory`|digest "Adapter base classes + lifecycle — Yes"|One Kalshi station-day captured to catalog, gap-audited|
|**S8**|**Station admission**: KDEN live recheck ≥2 days; KHOU archive-density sizing; **per-station CLI-final-vs-TWC reconciliation (n≥90, Wilson-lower >0.99, voids raise)**; `[sites.kalshi.*]` with narrow `body_header_regex` for the three same-office collisions|`config.py:16-29,88-95`; `sites.toml:13-16,94-104`|Each station ADMITTED/HELD with its own divergence rate; all six collision entries pass the sibling-decoy rejection test|
|**S9**|**Archive cells**: parser fix RED-first, extend `DENSE_STATIONS`, re-pull 2021–2025, emit **new** `archive_table_rev2.py`, **make the pin's source module selectable per config instance**|`generate_...:115-125,149-157`; `mb_...:20,30`; `config.py:261-264`|Every new cell ≥ n=90 or `n/a`; old pin byte-identical; a rev2-pinned config validates|
|**S10**|Kalshi instances (θ placeholder, Kalshi `fee_rounding_rule`, rev2 pin) in **SHADOW**|`config.py:226-239`; `decision.py:249-264`|Shadow candidates emitted; `orders_enabled` still refused; **per-station take rate MEASURED** — this number gates S12+|
|**S11** (operator)|Kalshi account, eligibility/KYC, funding, API key. **Operator-only, on the critical path**|n/a|Signed `GET /portfolio/balance` 200, fully redacted|
|**S12**|RSA-PSS signer behind `sign(bytes)->bytes`; separate canonical builder; **the three auth traps as tests**; S3' leak gate; live probe flips Kalshi's own verified flag|`signing.py:1,84,158-185`; `redaction.py:70-99`|Signed GET accepted; ms-timestamp / `/trade-api/v2`-prefix / query-stripped each fail RED-first; AST scan proves no monkeypatch path; no PEM line survives redaction|
|**S13**|**Per-venue permits (S2')**|`order_enablement.py:44,48,148,169-219`; `app/trade.py:178-190`|Cross-venue permit raises `TypeError`; Kalshi cannot mint on PM's flag|
|**S14**|`KalshiLiveExecutionClient` on `POST /portfolio/events/orders` (`side="bid"`, IOC, `self_trade_prevention_type="taker_at_cross"`, `client_order_id` latch), cancel/cancel-all/open-orders/fills, reconciliation; **shared ledger (S4')**; θ derived from the first `average_fee_paid`|`EXEC_SPINE_2026-09-01.md:959-969`; `operator_controls.py:250-285`|Ledger identity + two-submission race green; reconcile-before-resubmit proven with no reliance on venue duplicate-id behaviour; **Kalshi OP-SEQ** (rest → `?status=resting` → cancel by id → confirm absent) green under the operator ceiling|
|**S15**|Kalshi settlement: TWC-settled vs CLI-final reconciliation, venue-cash reconciliation, divergence rate; confirm the zero settlement leg on one held contract; measure the real settlement-delay clock for the registry|`EXEC_SPINE_2026-09-01.md:851-868`; `trial_scorer.py:187`|One realized-PnL row in the **Kalshi** family; divergence reported; voids **raise**|

## Tests

RED-first per step. New suites: Kalshi cage/firewall classification with the two mandated non-vacuity modules and the transitive-base case (S1); the blueprint's v1 non-modification pin, non-vacuous BE golden and mixed-θ fixture (S2); family-barrier refusal both directions (S3); registry live-verification contract incl. the five settlement-clock fields (S4); **one-instrument-per-ticker + BUY-YES-only + `side="bid"`; precision from `price_ranges[].step` incl. a sub-cent grid fixture; a test asserting NO cent field and NO `tick_size` read; `active`-not-`open`; strike-exclusivity incl. the `floor_strike` off-by-one and the `between` inclusive case; the three title/rules drifts (S5)**; fee-guard fail-closed + the `ceil_6dp`/per-order-accumulator arithmetic pinned against the documented worked example and later against a captured real fill (S6/S10/S14); 429 backoff constants pinned, `Retry-After` never read (S5); data-client tape-gap (S7); sibling-decoy rejection for KOKX/KPHI/KEWX, KHOU-not-KIAH, "TWIN CITIES MN"/"AUSTIN BERGSTROM" headers, `UnsupportedStationError` on a sub-threshold station (S8); parser 4-digit/8-digit T-group fixture, archive pin-mismatch and n≥90 generation, rev2-pin selectability (S9); **three auth traps + multi-line-PEM leak assertions (S12)**; cross-venue permit `TypeError` (S13); ledger identity + two-submission race + latch idempotence via reconcile-before-resubmit mirroring `tests/contract/test_exec_client_{wiring,reconciliation}_contract.py` (S14); settlement `px ∈ {0,1}` **raises** on void (S15). **Every barrier change is a coverage widening** — no predicate relaxed, no PM barrier edited except to add the Kalshi path/host/SDK/name sets and the transitive base closure.

## Risks

- **Duplicate NWS polling on shared stations** — registering `[sites.kalshi.*]` makes `kalshi:LAX` etc. selectable; if ever added to the running ingest unit alongside `polymarket_us:LAX`, two actors poll one CLI product and a UA-trap 403 burst lands on the LIVE PM ingest. Registry entry ≠ ingest site (S4 exit).

- **θ unobtainable without the operator.** The coefficient exists only in a PDF that 429s non-browser clients. Mitigation: first-fill derivation from `average_fee_paid` is a complete substitute; until either lands, Kalshi is shadow — this blocks a *verdict*, not the build.
- **Duplicate-`client_order_id` semantics UNVERIFIED.** Mitigation: the latch never relies on venue dedupe; reconcile-before-resubmit is the primary mechanism.
- **Settlement-source divergence (TWC vs CLI).** The load-bearing admission test, unmeasured for every candidate. A station that fails Wilson-lower >0.99 is excluded, not down-weighted.
- **KDEN/KHOU HELD** on live-feed and archive-density grounds respectively; both could be permanently excluded.
- **Same-office product capture** — KOKX/KPHI/KEWX each issue two of our CLI products; a broad regex mis-settles a trial. Mitigated by narrow regexes + sibling-decoy tests for all six entries.
- **Kalshi take rate is unknown** (0.25 is Polymarket's). S10 shadow measures it; re-size S12+ from that number.
- **Archive-cell attrition** — cadence PASS does not guarantee ≥90 samples per `(station, season, hour, width, m)` cell. S9 reports per-station admitted-cell counts before S10 wires anything.
- **Permit inheritance (S2')** — Kalshi execution silently enabled by PM's now-`True` flag. Highest severity; S13 lands before S14.
- **Ledger split** — a second process silently doubles the operator's daily cap. Mitigated by the identity test + single-process deploy statement.
- **Corpus/pin drift** and the `config.py:261-264` single-module pin — mitigated by S9's selectable pin plus stratify-or-refuse.
- **IEM rate limits on the re-pull** — a 19-station five-year pull is the largest archive request this repo has made. Budget wall-clock, back off, checkpoint.
- **Fixed-point migration drift** — vendor deprecations are dated (cent fields removed 2026-01-15, `tick_size` removal 2026-05-07, legacy order path/fields ~2026-05/06). Mitigation: no code path may depend on a deprecated field, and the S0 vendor snapshot is re-pulled before S14.
- **Displacement** — any Kalshi step requiring an edit to the live PM path is a stop-and-replan.

## Effort

Build-days, one focused implementer, excluding operator wall-clock.

| Stage | Steps | Days | Kalshi events/day after |
|---|---|---|---|
| Probe | S0 | **DONE** | 0 |
| Barriers + v2 tally path | S1–S3 | 3–4 | 0 |
| Read path | S4–S7 | 5–7 | 0 (data only) |
| Admission + cells | S8–S9 | 6–9 (+2–4 d wall-clock, IEM-limited) | 0 |
| Shadow | S10 | 1.5 | 0 scored; take rate measured |
| Write path | S12–S15 (S11 operator-gated) | 8–12 | see below |
| **Total** | | **24–34 build-days** | |

## What this buys

Kalshi's clock starts at **Kalshi D0** — the first UTC day after (a) the sibling PREREG is committed and (b) a Kalshi-only tally is actually running v2 boundaries — with **n = 0**. The PM family's clock is unchanged.

Station ceiling: **4 existing + 18 gate-1-passing (KDEN/KHOU HELD) = up to 22 TOTAL**. Arithmetic at the **observed** 0.25 taken trials/station-day. Under PREREG v2 (looks every 10 fills, **n_max=160**), the fixed n=150 floor is look 15, not a verdict; **n=60 is a KILL-only milestone** — SURVIVE additionally requires `not cell_dead` and ΣPnL>0. **No column below is a verdict date.**

| Total stations | Events/day | n=60 (KILL milestone) | n=160 (horizon) |
|---|---|---|---|
| 8 (attrition / cell-thin bad case) | 2.0 | D0 + 30 d | D0 + 80 d |
| 15 | 3.75 | D0 + 16 d | D0 + 43 d |
| 22 (all admitted) | 5.5 | D0 + 11 d | D0 + 30 d |

**Station-multiplying DILUTES the stratum-OR kill**: each station stratum needs ~240 days to reach n=60 at 0.25/station-day, so the fastest single-cell kill lever slows as stations grow. The go/no-go for S11–S15 is **S8's per-station divergence result plus S9's admitted-cell count**, not the cadence results already in hand.

## Operator items (explicit — nothing else in this plan is an operator decision)

1. **Kalshi account, eligibility/KYC approval, funding, and API-key issuance** (S11). On the critical path; wall-clock outside Breezy's control; **the single largest schedule uncertainty**. Eligibility text is unquotable from any non-browser client (§Venue mechanics) — an operator determination, not a build item.
2. **Fee schedule**: fetch `kalshi.com`'s fee-schedule PDF **in a browser** and drop it under `docs/evidence/venue/kalshi/` — **or** accept first-fill derivation of θ from `average_fee_paid` (S14). Either closes the θ blocker; neither is required before S10.
3. **The two spend caps stay exactly as-is**, operator-reserved and unassigned by the repo. Because both venues share **one** `DailySpendLedger` in **one** process, enabling Kalshi does **not** raise total daily spend unless the operator raises that one existing number.

## Review log

| # | Finding | Resolved in |
|---|---|---|
| R1 | Sibling family, never pooled; Option P deleted; speed lever is new stations | Goal; Tally |
| R2 | Shadow is a diagnostic prefix only; no retroactive scoring | Goal; S10 |
| R3 | Own `P_HOLD_LOWER` cells at n_min=90; cadence rule defined and measured | Stations; S8, S9 |
| R4 | Per-station CLI-final-vs-venue-settled reconciliation, divergence not inherited — **now load-bearing, TWC vs CLI** | Venue mechanics (settlement); Stations; S8, S15 |
| F1 | Break-even is a module constant; per-trial BE is **v2/Kalshi-only**, v1 byte-identical; fee is **concave** so v1's form is conservative | Tally; S2 |
| F2 | Venue provenance via trial-id prefix + family manifest; `venue:` stratum; no pooled path; **no `ScoredTrial` schema change** | Tally (blueprint); S2–S3 |
| F3 | S9/S14 20–30% under; IEM rate limits | Effort; Risks |
| F4 | `KalshiFeeModel(FeeModel)`; config rule field validated like frozen-for-life fields | Fees; S6 |
| F5 | **REWRITTEN**: no NO-ticker; ONE instrument per market ticker, BUY-YES-only `side="bid"`; the old two-instrument exit is deleted | Venue mechanics; S5; Tests |
| F6 | Both take-rate figures named; projections use the observed 0.25 | Goal; What this buys |
| F7 | Live series-listing check — DONE, cited | Inventory; Stations |
| S1' | Firewall/cage widened; **E2 = transitive base-name closure** (not MRO); SDK constant at **six** sites | Execution & safety; S1 |
| S2' | Per-venue permit types, own flags, submit-path `TypeError` | Execution & safety; S13 |
| S3' | RSA-PSS leak gate + fail-closed load + runbook shell-only | Execution & safety; S12 |
| S4' | One process, one ledger; identity test; deploy statement; race test | Execution & safety; S14 |
| Cadence | Rule **PINNED at median-of-daily-medians ≤5 min AND ≥90% of days**; ≥95% figure superseded; two sample months PASS; temp-bearing gate; **KDEN/KHOU HELD** | Stations; S8; Risks |
| Parser | 4-digit T-group defect; rev2-only fix; density re-measured, never applied to v1 | Stations; S9 |
| Pin | `config.py:261-264` single-module pin blocks "rev2 + old untouched" until selectable | Stations; S9 |
| Seq | Read + admission + cells + shadow first; write path gated on measured take rate; Stage B on PM impossible | Goal; Build order |
| S0-1.6 | Status vocabulary is `active`, not `open`; filter map recorded | Venue mechanics; S5; Tests |
| S0-1.7 | 429 carries **no** `Retry-After`/`X-RateLimit-*`, no cooldown → backoff pinned in-repo, header never read | Venue mechanics; S5; Tests |
| S0-3.5/3.7 | Strikes EXCLUSIVE (`between` inclusive); `expiration_time` **deprecated** → use `latest_`/`expected_expiration_time`; never parse tickers for relationships | Venue mechanics; S5 |
| S0-4.1/4.3 | Fixed-point dollar strings (`*_dollars`, `*_fp`); **integer-cent fields removed 2026-01-15** → symbology/parsing never handle cents; no published `[0.01,0.99]` bound | Venue mechanics; S5; Tests |
| S0-5.2 | θ **UNVERIFIED** (PDF 429s non-browser clients); derivable from first fill `average_fee_paid`; form VERIFIED quadratic/×1 | Fees; Operator items 2; S14 |
| S0-5.4 | Rounding is `ceil_6dp(model_fee)` + **per-ORDER accumulator** with rounding fees/rebates — not round-up-to-cent; `fee_rounding` → **`fee_rounding_rule`** | Fees; S6 |
| S0-5.5 | Settlement fee **ZERO** for simple yes/no (VERIFIED) → `trial_scorer.py:187` holds; confirm on one settlement | Fees; S15 |
| S0-6.1 | **No NO-ticker**; `bid`=buy YES, `ask`=sell YES; one signed position | Venue mechanics; F5; S5 |
| S0-6.3/6.4 | `tick_size` **deprecated → never read**; precision from `price_level_structure`/`price_ranges[].step`; min granularity 0.01 contracts (Breezy stays at 1); min notional UNVERIFIED | Venue mechanics; S5 |
| S0-6.5 | `POST /portfolio/events/orders`; `side ∈ {bid,ask}`; **IOC exists**, no GTT; `expiration_time` seconds, IOC-incompatible; `self_trade_prevention_type` REQUIRED → `taker_at_cross`; cancel/cancel-all/open-orders/fills paths → **OP-SEQ mapping** | Venue mechanics; S14 |
| S0-6.5b | **`client_order_id` EXISTS → R-7 latch re-decided**: latch key = `client_order_id`; duplicate-id behaviour **UNVERIFIED** (vendor silent) → reconcile-before-resubmit is the authority | Venue mechanics; S14; Risks |
| S0-7.1/7.2/7.3 | RSA-PSS SHA256 MGF1-SHA256 salt=32 base64; timestamp **ms**; canonical `ts+METHOD+path` with `/trade-api/v2` **included**, query **stripped** → three named tests | Execution & safety; S12; Tests |
| S0-10.4 | Settlement source is **TWC** (rules + `settlement_sources`), CLI names the station; expiration = sooner of first 7:00/8:00 AM ET after data release **or one week**; `settlement_timer_seconds` 300 → registry values stated, delay pair flagged unverifiable | Venue mechanics (registry fields); S4; S15 |
| S0-14.1 | Eligibility/KYC unquotable, **operator-only** | Operator items 1 |
