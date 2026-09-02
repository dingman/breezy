---
name: polymarket-us-integration
description: Polymarket.us retail API, Ed25519 signing, market structure, weather settlement timing, venue fee formula, and error taxonomy for Breezy's Polymarket.us adapter implementation.
---

# Polymarket.us Integration Reference

## ⚠️ BANNER — Polymarket.us is NOT Polymarket.com

**Never assume shared APIs, authentication, endpoints, market structure, or settlement logic.**

The bundled Nautilus `adapters/polymarket/` targets **Polymarket.com** (Polygon CLOB, EIP-712 wallet signature, USDC). It is **structurally unusable** for Polymarket.us.

| Dimension | Polymarket.us | Polymarket.com |
|-----------|--|--|
| Regulation | CFTC DCM+DCO | Unregulated crypto |
| Settlement Currency | Fiat USD | USDC on Polygon |
| Custody Model | Polymarket Clearing (DCO) | Self-custodied wallet (on-chain) |
| Auth | Ed25519 request signing | EIP-712 wallet signature |
| Host | api.polymarket.us | clob.polymarket.com |
| ID Scheme | Slug (aec-nfl-kc-phi-2026-02-09) | condition_id + ERC-1155 token_id |
| Resolution | Exchange Rulebook, Polymarket settlement | UMA optimistic oracle |
| KYC Required | Yes (US residents) | No |

---

## Venue Identity

- **Operator**: Polymarket US, Inc. — CFTC-regulated DCM (Designated Contract Market) and DCO (Derivatives Clearing Organization) via acquired QCX LLC / QC Clearing LLC.
- **Geography**: US residents only. KYC-gated account opening via docs.polymarket.us.
- **Currency**: USD (fiat), settled via Polymarket Clearing DCO.

---

## API Stacks

### Stack A: Retail / Developer

- **Base URL (authenticated)**: `https://api.polymarket.us/v1/`
- **Base URL (public)**: `https://gateway.polymarket.us/`
- **WebSocket (private)**: `wss://api.polymarket.us/v1/ws/private`
- **WebSocket (markets)**: `wss://api.polymarket.us/v1/ws/markets`
- **Official SDKs**: 
  - Python: `polymarket_us` (github.com/Polymarket/polymarket-us-python)
  - TypeScript: `polymarket-us`
- **Rate Limits**: 20 req/s per API key (auth) / per IP (unauth); 429 response on breach.
- **Known bug**: Orders not processed within 5 seconds reject with message "Global Rate Limit Exceeded" — this is a stopgap rate-gate, not an actual rate limit. Disambiguate via retry logic.

### Stack B: Institutional Exchange

- **Base URL (REST)**: `https://api.prod.polymarketexchange.com/` (preprod: `api.preprod...`)
- **gRPC**: `grpc-prod.polymarketexchange.com:443`
- **FIX**: AWS PrivateLink / VPC only
- **Credentials**: Obtained via `onboarding@polymarket.us` — separate onboarding flow.

**Retail never reaches Stack B.** Stack B requires institutional status and separate credentials.

---

## Authentication (Retail Ed25519 Signing)

**NOT EIP-712, NOT a wallet.** Ed25519 request signing on a per-request basis.

### Request Headers

- `X-PM-Access-Key`: UUID key_id (non-secret, identifies your API key)
- `X-PM-Timestamp`: milliseconds since epoch (must be within 30 SECONDS of server time)
- `X-PM-Signature`: base64-encoded Ed25519 signature over the canonical string

### Canonical String Construction

```
<timestamp_ms> + <HTTP_METHOD> + <request_path>
```

Example:
```
1234567890000GET/v1/portfolio/positions
```

**Critical details**:
- Include trailing slash if the path carries one.
- **Query string is EXCLUDED** — the canonical string is `timestamp + HTTP method + path` over the BARE path.
  Evidence: `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_authentication_2026-08-25.md:82`
  ("combining the timestamp, HTTP method, and path") and its worked example at line 94
  (`message = f"{timestamp}{method}{path}"`); Polymarket's own SDK signs path-only at
  `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/auth.py:27`, building query
  parameters separately. No venue source states that the query string is signed.
- Sign the exact bytes of this concatenation using your Ed25519 private key.
- Timestamp must be within 30 SECONDS of server time or the request fails silently.

### Secret Key

- Format: base64-encoded Ed25519 private key.
- Shown **once** during API key generation.
- Non-recoverable — keep the base64 string secure and rotate immediately if exposed.
- KYC account opening MUST precede API key issuance.

### Mandatory Unit Tests

HARD GATE before production deployment:

1. **Known-vector test**: fixed timestamp, method, path → expected signature (test against official SDK output or reference vectors).
2. **Clock-skew boundary tests**: timestamp ±29s, ±30s, ±31s → acceptance/rejection.
3. **Canonical-string construction tests**:
   - Paths with/without trailing slash.
   - Query strings (param order, special characters, encoding).
   - HTTP methods (GET, POST, DELETE).
   - Signature byte ordering (UTF-8 encoding correctness).

**Why mandatory**: Clock drift is a silent total-auth-failure mode. It deserves runtime monitoring and alerting.

---

## Authentication (Institutional OAuth2 / Auth0)

- **Token Endpoint**: `https://pmx-prod.us.auth0.com/oauth/token`
- **Grant Type**: private-key-JWT (client assertion)
- **Signature Algorithm**: RS256 (RSA SHA256)
- **Access Token Lifetime**: 180 seconds — refresh approximately every 3 minutes with a 30-second buffer.
- **Not for retail — forward-compat note only.**

---

## Market Structure

- **Hierarchy**: Series → Events → Markets
- **Primary Identifier**: **slug** (e.g., `aec-nfl-kc-phi-2026-02-09`)
  - Used for orders, order books, WebSocket subscriptions.
  - Human-readable format: typically `<abbreviation>-<sport/event>-<details>-<date>`.
- **Settlement**: Binary $1.00 / $0.00 per outcome.
- **Exceptions**: Some markets carry non-standard predefined settlement terms in the `description` and `rulesDisclaimer` fields.

---

## Order Fields

| Field | Type | Enum / Notes |
|-------|------|---|
| `marketSlug` | string | Required. Primary market identifier. |
| `type` | enum | `ORDER_TYPE_LIMIT` \| `ORDER_TYPE_MARKET` |
| `price` | object | `{value: decimal, currency: string}` |
| `quantity` | decimal | See per-market `minimumTradeQty`. |
| `tif` | enum | `DAY`, `GOOD_TILL_CANCEL`, `GOOD_TILL_DATE`, `IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL` |
| `intent` | enum | `ORDER_INTENT_BUY_LONG`, `SELL_LONG`, `BUY_SHORT`, `SELL_SHORT` |
| `outcomeSide` | enum | `OUTCOME_SIDE_YES`, `OUTCOME_SIDE_NO` |
| `action` | enum | `ORDER_ACTION_BUY`, `ORDER_ACTION_SELL` |
| `participateDontInitiate` | bool | Post-only flag. |
| `cashOrderQty` | bool | Rare, document usage. |
| `slippageTolerance` | object | `{currentPrice, bips, ticks}` |
| `manualOrderIndicator` | bool | Rare. |

**UNRESOLVED**: `intent` × `outcomeSide` × `action` have **no documented precedence or required-combination matrix**. Resolve empirically per market.

---

## Tick Size & Minimum Quantity (Per-Market, NOT Global)

**Never hardcode global constants.**

Each market carries:
- `orderPriceMinTickSize` — minimum price increment for limit orders.
- `minimumTradeQty` — minimum order quantity for that market.

Retrieve via `GET /v1/market/slug/{slug}` on gateway.polymarket.us.

**UNRESOLVED**: whether decimal quantities are supported when `minimumTradeQty` < 1. One doc says yes; another says "all trades executed in whole contracts." Resolve empirically.

---

## Fee Formula

**Effective 2026-07-01.**

```
Fee = Θ × C × p × (1 − p)
```

Where:
- `C` = contract quantity
- `p` = execution price (0 to 1, binary outcome)
- `Θ` = taker or maker coefficient

| Role | Θ | Notes |
|------|---|-------|
| Taker | 0.06 | Max $1.50 per 100 contracts at p=0.50 |
| Maker | −0.0125 | Rebate (negative fee). |
| Taker Rebate (Tier 1) | 0.054 | $250K+ monthly volume (10% off taker fee). |
| Taker Rebate (Tier 2) | 0.045 | $1M+ monthly volume (25% off). |
| Taker Rebate (Tier 3) | 0.03 | $10M+ monthly volume (50% off). |

**Rounding**: banker's rounding to $0.01.

**Free scenarios**: Cancelled, expired, or rejected orders incur no fee.

---

## Weather Markets & Settlement Timing

### Settlement Source

Verbatim from venue: "the official NWS Daily Climate Report (CLI) published by the local Weather Forecast Office."

### Five-City Mapping (Fixed)

| City | ICAO Site | CLI Location | Issuing WFO |
|------|-----------|--------------|---|
| NYC | KNYC | CLINYC | KOKX |
| San Francisco | KSFO | CLISFO | KMTR |
| Miami | KMIA | CLIMIA | KMFL |
| **Chicago** | **KMDW** | **CLIMDW** | **KLOT** |
| Los Angeles | KLAX | CLILAX | KLOX |

**Authoritative Source**: The table above is illustrative; the single source of truth is `src/breezy/registry/sites.toml`, keyed by `(venue, city)`. That registry must not drift from this skill. Update both together.

**CRITICAL**: Chicago uses **KMDW (Midway), NOT O'Hare (KORD)**.

**Identifier Distinction**: The **CLI Location** column (e.g., `CLINYC`) is the AWIPS PIL, found on line 3 of the published CLI product text. The NWS API path `/products/types/CLI/locations/{loc}` uses the **bare three-letter code** (e.g., `NYC`, `SFO`, `MIA`, `MDW`, `LAX`). These are different identifiers in different positions — do not conflate them.

**Office Collision Hazard**: One WFO often issues CLI products for multiple cities under a single `issuingOffice`: KOKX issues NYC+JFK+LGA+EWR; KLOT issues MDW+ORD; KLOX issues LAX+BUR+LGB; KMTR issues SFO+OAK+SJC; KMFL issues MIA+FLL+APF. The `issuingOffice` field alone cannot bind a CLI product to a market. Use per-city product-body header regex to extract the correct station.

### Settlement Timing

- **Standard**: Settlement occurs at **08:00 AM ET** on the calendar day after the contract's specified date.
- **Conflict Branch**: "If the CLI reading is inconsistent with the 24-hour METAR observation for the same location, settlement may be delayed until **11:00 AM ET** for review." This opens a review window; 08:00 ET is not the only settlement instant.
- **Fallback**: "If no data is published within one week of the scheduled release, the Contract settles at last fair market prices."
- **Measured Quantities**: Observed **high, low, and average** temperatures.
- **Per-Market Rules**: Exact settlement terms live in Market `description` and `rulesDisclaimer` fields.

**Provenance**: Venue settlement rules text can change silently between nominally identical daily markets. The authoritative snapshot of the current ruleset is maintained in `docs/evidence/venue/polymarket_us/` (dated, content-digested, append-only — never edited in place). This skill is a convenience summary; use the evidence of record for disputes or when integration behavior diverges from this text.

---

## Rate Limits & Error Taxonomy

- **20 requests/second** per API key (authenticated) or per IP (public).
- **429 response** on breach → backoff + circuit breaker mandatory.
- **"Global Rate Limit Exceeded" message** on orders not processed within 5 seconds → this is a stopgap gate, not an actual rate limit. Retry with exponential backoff.

---

## Known Contradictions & Unresolved Questions

All flagged as **UNRESOLVED** — empirical resolution required:

1. **Decimal vs whole contracts**: `create-order` docs say decimals supported where `minimumTradeQty` < 1. Separate doc says "all trades executed in whole contracts." Requires per-market testing.

2. **Enum precedence**: `intent` × `outcomeSide` × `action` are three overlapping "optional" fields. No documented required-combination matrix. Resolve via order submission tests.

3. **Gateway CORS**: `gateway.polymarket.us` returns 403 to non-browser fetches. Fetch requirement or bug? Test empirically.

4. **Exchange Rulebook URL**: No public URL located. Institutional only or not published online?

5. **Weather slug grammar**: Only sports example documented (aec-nfl-kc-phi-2026-02-09). Weather slug format undocumented.

6. **Retail key reach**: Can retail Ed25519 keys reach gRPC or FIX endpoints? Documentation is silent.

7. **Sandbox availability**: No retail sandbox documented. Preprod (`api.preprod.polymarketexchange.com`) is institutional-only.

8. **WebSocket schemas**: Subscribe message schema, auth-on-connect behavior, heartbeat / reconnect semantics not documented.

9. **Market halt behavior**: What happens around CLI publication windows (08:00 ET / 11:00 ET)? Trading halt? Quote-only mode?

---

## Forward Compatibility Note: Kalshi

Kalshi (phase 2) uses a near-identical request-signing recipe:
- Headers: `KALSHI-ACCESS-KEY` / `-TIMESTAMP` / `-SIGNATURE`
- Canonical string: `timestamp + METHOD + path` (same)
- Algorithm: **RSA-PSS SHA256** (NOT Ed25519 — different failure surface)

**Sanctioned shared seam**: `sign(bytes) -> bytes` abstraction only.

**Separate**: Canonical-string builders remain venue-specific. Ed25519 and RSA-PSS have different salt lengths, hash mismatches, and verification failures. Do NOT try to unify them.

---

## Discovery Log (Append-Only)

**Format**: Each entry carries `endpoint`, `market_slug`, request/response *schema facts only*, `date`, and a `provisional: true/false` flag.

**Rules**:
- A fact stays `provisional: true` until **reproduced on ≥2 distinct markets** and signed off by `python-reviewer` or `prediction-market-reviewer`.
- **NEVER** include `secret_key`, signatures, raw headers, or full response bodies.
- `key_id` (UUID) is the only credential-adjacent value ever permissible.
- **Staleness trigger**: >90 days since last verified entry → re-dispatch `polymarket-us-discovery` agent with a named owner.

| Date | Endpoint | Market Slug | Finding | Provisional | Notes |
|------|----------|-------------|---------|-------------|-------|
| 2026-08-30 | `GET gateway /v1/markets` | 60 open climate markets | **Reference-data market object carries `slug`, NOT `marketSlug`.** Top-level fields: `active, archived, bestAskQuote*, bestBidQuote*, category, closed, comboEnabled, createdAt, description, endDate, ep3Status, ep3SyncedAt, feeCoefficient, gameStartTime, hidden, id, manualActivation, marketSides, marketType, minimumTradeQty, orderPriceMinTickSize, outcomePrices, outcomes, question, slug, sortOrder*, sportsMarketType, sportsMarketTypeV2, startDate, status, tags, title*, titleShort*, updatedAt` (`*` = present on climate, absent on sports). No `rulesDisclaimer` field exists on either list or by-slug reads. | true | Reproduced on 60 markets + 4 by-slug reads. |
| 2026-08-30 | `WSS /v1/ws/markets` | `tc-temp-nychigh-2026-08-30-gte82lt83f`, `tc-temp-miahigh-2026-08-30-gte91lt92f`, `tc-temp-sfohigh-2026-08-30-gte70lt71f`, `tc-temp-nychigh-2026-08-30-gte90f` | **`marketSlug` CONFIRMED as the market-data frame key, nested one level under `marketData`.** Frame envelope = `{marketData, requestId, subscriptionType}`; `subscriptionType` = `SUBSCRIPTION_TYPE_MARKET_DATA`; `requestId` = 32-char lowercase hex. Path `marketData.marketSlug` (str) present on 108/108 market_data frames across two sessions. | true | Reproduced on 4 markets (direct probe) + 10 markets (smoke run). |
| 2026-08-30 | `WSS /v1/ws/markets` | 60 climate slugs (one connection) | **Undocumented cap: 10 market-data subscriptions per WebSocket connection.** Subscribing 60 slugs on one connection yielded 10 accepted + 50 error frames. Error frame shape: `{error: str, requestId: str}`, `error` = `"max subscriptions per connection reached"`. Subscribing 4 slugs yielded 0 errors. | true | Reproduced across 2 sessions (60-slug run, 4-slug run). |
| 2026-08-30 | `GET gateway /v1/markets`, `/v1/market/slug/{slug}` | 60 open climate + 200 resolved climate + 200 sports | **Per-market, confirmed non-global.** Weather (climate/`futures`): `orderPriceMinTickSize` = `0.01`, `minimumTradeQty` = `0.01`, `feeCoefficient` = `0.06` on 60/60. Sports (`moneyline`): `orderPriceMinTickSize` = `0.001`, `minimumTradeQty` = `1` on 200/200. `minimumTradeQty` < 1 on weather is direct evidence for fractional quantities. | true | Reproduced on 260 markets across 2 categories. |
| 2026-08-30 | `GET gateway /v1/markets?categories=climate` | `tc-temp-*` (5 cities) | **Weather slug grammar confirmed:** `tc-temp-<city><measure>-<YYYY-MM-DD>-<bounds>`. City tokens observed: `nyc`, `mia`, `mdw`, `lax`, `sfo`. `measure` observed: `high` only. `bounds` = one or two comparator tokens then `f`; comparators observed: `gte`, `lt`. Shapes: `lt<NN>f`, `gte<NN>lt<NN+1>f`, `gte<NN>f`. Hypothesised `between<NN>f` token does NOT occur. | true | Reproduced on 60 open + 200 resolved climate markets. |
| 2026-08-30 | `GET gateway /v1/markets` (no `categories`) | full unfiltered walk, 2599 markets | **Climate markets are absent from the unfiltered listing.** An offset walk to exhaustion (offset 0..2400, short page at 2400) returned zero `tc-*` slugs. `categories=climate` is REQUIRED for weather discovery; the default listing is sports-only. Envelope is `{markets: [...]}` with no cursor field; pagination is `limit`+`offset`. | true | Single unfiltered walk; corroborated by the filtered query returning 60. |
| 2026-08-30 | `GET api /v1/portfolio/positions` | n/a (account-scoped) | **Query string is NOT part of the signed canonical string.** Same request signed path-only → `200`; signed path+query → `401`. Canonical string is `timestamp + METHOD + path`. | true | Reproduced on 3 independent smoke runs. |
| 2026-08-30 | `GET api /v1/portfolio/positions` | n/a (account-scoped) | **The documented ±30 s timestamp window is NOT enforced.** A deliberately stale `X-PM-Timestamp` at −120 s was ACCEPTED with `200`. Do not rely on the venue to reject skewed timestamps; a local clock guard remains the only control. | true | Reproduced on 3 independent smoke runs. |
| 2026-08-30 | `WSS /v1/ws/markets` | n/a | **The markets WebSocket requires authentication.** An unauthenticated connect failed with a transport error on every attempt. | true | Reproduced on 3 independent smoke runs. |
| 2026-08-30 | `GET gateway /v1/markets` | `tc-temp-nychigh-2026-08-30-gte84lt85f`, `-gte90f`, `tc-temp-miahigh-2026-08-30-gte87lt88f`, `tc-temp-mdwhigh-2026-08-30-gte92lt93f` | **`outcomes` array ordering is NOT stable and does NOT index `outcomePrices`.** 4/60 open markets returned `outcomes` = `["No","Yes"]` while `outcomePrices` and `marketSides` stayed in Yes-then-No order. `outcomePrices` is also sometimes length 1 (13/60). Use `marketSides[].long` (bool) + `marketSides[].description` for side identity; never `outcomes` index position. | true | Reproduced on 4 markets. |
| 2026-08-30 | `GET gateway /v1/markets/{slug}/book`, WS market_data | `tc-temp-nychigh-2026-04-22-gte56lt57f`, `tc-temp-nychigh-2026-04-22-gte62lt63f` | **Terminal-settlement gate confirmed against live expired markets.** `marketData.state` = `MARKET_STATE_EXPIRED` co-occurs with `stats.settlementPriceCalculationMethod` = `SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1` and `settlementPx` ∈ {`1.0000`, `0.0000`}; open markets carry `MARKET_STATE_OPEN` with `..._EVENT_TIER_2` (a daily mark) or no method key at all. | true | Reproduced on 2 expired markets + 60 open markets. |
| 2026-08-30 | `WSS /v1/ws/markets` | `tc-temp-nychigh-2026-08-30-gte90f` | **One-sided books occur live:** market_data frames arrive with `marketData.bids` = `[]` (5/5 frames on this slug). Any top-of-book consumer must handle an empty side; it is a normal venue state on deep-out-of-the-money strikes, not a malformed frame. | true | Reproduced on 5 frames, 1 market + observed on 5 further slugs in smoke logs. |
| 2026-08-30 | `GET gateway` path shapes | 4 weather markets | **Path grammar diverges from the published docs.** `/v1/market/slug/{slug}` → `200` (singular, `{market: {...}}` envelope). The documented `/v1/markets/{slug}` → `404`. `/v1/markets/{slug}/book` → `200` and `/v1/markets/{slug}/bbo` → `200` (plural). `/v1/markets/{slug}/settlement` → `404` on both open and expired markets. | true | Reproduced on 4 open + 2 expired markets. |
| 2026-08-30 | `GET gateway /v1/markets/{slug}/bbo` | 4 weather markets | **`/bbo` omits `transactTime`.** Its `marketData` carries `askDepth, bestAsk, bestBid, bidDepth, currentPx, lastPriceSample, lastTradePx, longQuote, marketSlug, openInterest, settlementPx, sharesTraded, shortQuote, state` — no `transactTime` and no `bids`/`offers`. `/book` and WS market_data frames DO carry `transactTime`. | true | Reproduced on 4 markets. |
| 2026-08-30 | `GET gateway /v1/markets` | all | **G15 refuted: `gateway.polymarket.us` answers a non-browser client.** Every public read in this session returned `200` with a plain contact User-Agent. No 403 was observed on any gateway path. | true | Reproduced across ~25 gateway requests this session. |
| 2026-08-30 | n/a | n/a | **UNRESOLVED — `intent` × `outcomeSide` × `action` precedence matrix.** Requires order submission; needs an operator exception with a named USD capital ceiling. Not attempted. | true | No read-only surface exposes the precedence rules. |
| 2026-08-30 | n/a | n/a | **UNRESOLVED — decimal-vs-whole-contract contradiction.** `minimumTradeQty` = `0.01` on all 60 weather markets is strong evidence FOR fractional quantities, but acceptance can only be proven by submitting an order. Needs an operator exception with a capital ceiling. | true | Partial evidence only; not settled read-only. |
| 2026-08-30 | n/a | n/a | **UNRESOLVED — whether retail Ed25519 keys reach gRPC/FIX**, and **the Exchange Rulebook** (no public URL found). Neither is reachable from an allow-listed read. | true | Not attempted; out of read-only scope. |
| 2026-08-30 | `WSS /v1/ws/markets` | 60 open climate slugs, one connection, ONE SLUG PER SUBSCRIBE ENVELOPE | **The 10-subscription cap is SILENT when slugs are subscribed one-per-envelope.** 60 sequential single-slug subscribe envelopes (60 distinct `requestId`s) produced **ZERO** `max subscriptions per connection reached` frames, and only **1** inbound frame lacking `marketSlug` over a 6m11s run. Market data then arrived for **exactly the first 10 slugs in subscribe order** and for no other; slugs 11-60 yielded no frames of any kind. The cap is therefore real at 10, but its observable signal DEPENDS ON THE SUBSCRIBE PATTERN: batched (60 slugs in one envelope) yields explicit error frames, one-per-envelope yields silent truncation. **Absence of cap error frames does NOT prove a subscription is live.** | true | 1 recorder session, 60 slugs; complements the earlier batched-subscribe session that DID error. Needs a second one-per-envelope session. |
| 2026-08-30 | `WSS /v1/ws/markets` | `tc-temp-nychigh-2026-08-30-gte86lt87f`, `-gte88lt89f`, `-gte90f`, `tc-temp-miahigh-2026-08-30-lt87f`, `-gte87lt88f` | **One-sided books cost the ENTIRE quote and depth record, not just one side.** All 5 slugs whose `bestBidQuote` was `None` at discovery produced 247 `Could not parse quote ... VenuePayloadError` errors and **zero** `quote_tick` / `order_book_depths` rows over the run, while the other 5 captured slugs recorded 675 of each. `parse_book_top` (`parsing.py:582`) requires a best level on BOTH sides, so an empty `bids` array aborts the whole frame. `mark_price_update` and `custom_venue_settlement_snapshot` were still captured for these slugs (10 instruments), so the loss is confined to top-of-book and depth. | true | Reproduced on 5 distinct markets in 1 session. |
| 2026-08-30 | `GET gateway /v1/markets?categories=climate` | 60 open climate markets | **Open weather universe is a fixed 5 cities x 2 climate days x 6 strikes = 60.** A complete strike ladder is exactly **6** slugs, comfortably under the 10-subscription cap. Ladder shape per city-day: one `lt<N>f`, four `gte<N>lt<N+1>f`, one `gte<N>f`; strikes step by 2 degF so the labelled bounds are NOT contiguous, yet best-bid across the 6 sums to ~0.98 (e.g. MDW 2026-08-31: 0.30+0.26+0.09+0.03+0.01+0.29), i.e. the venue prices the ladder as an exhaustive partition. `orderPriceMinTickSize`=0.01 and `minimumTradeQty`=0.01 on 60/60. | true | Reproduced across 10 city-day ladders (60 markets) in 1 read-only walk. |
| 2026-08-30 | recorder startup (`breezy-quote-tape`) | all 60 discovered slugs | **Spurious startup ERROR storm: 60 `cache.instrument(...) is None after publishing instruments to the data engine` lines per discovery cycle.** `_alert_on_missing_cache_after_push` (`data.py`) runs BEFORE the `await` in `_reconcile_discovered_subscriptions`, so the DataEngine has not yet drained its instrument queue. The very next reconcile then subscribed all 60 with `blocked_missing_cache=()`, proving the cache WAS populated. Diagnostic race, not a data fault, but it emits 60 ERROR lines per cycle and would trip any error-rate alert. | true | Reproduced on 5 discovery cycles in 1 session (12 slugs x 5 cities). |
| 2026-09-02 | `GET api /v1/portfolio/activities` | n/a (account-scoped) | **Authenticated private read SUCCEEDS: HTTP `200` with a parsed envelope `{activities: array, eof: bool, nextCursor: string}`.** The private surface uses CURSOR pagination (`eof` bool + `nextCursor` string), not limit/offset as the public `/v1/markets` listing does. `unrecognized_key_count` = 0, so no key drifted from the committed SDK TypedDicts. **Account is EMPTY**: `activities` rendered as a bare `array` with no `items` node, which the shape grammar emits only for a zero-element list — so the per-activity item shape is UNOBSERVED, and a future reader must not read its absence as 'the venue sends no item fields'. | true | Single observation, one path, one account. Needs a second run on a non-empty account before promotion. |
| 2026-09-02 | `GET api /v1/account/balances`, `/v1/portfolio/positions`, `/v1/orders/open` | n/a (account-scoped) | **Private backend degraded, deterministically and per-endpoint — NOT an auth failure.** `/v1/account/balances` → `500` / grpc `code` 13 (INTERNAL); `/v1/portfolio/positions` and `/v1/orders/open` → `503` / grpc `code` 14 (UNAVAILABLE). Identical on every attempt across ~10 minutes. Discriminators run in the same session: the SAME path with NO credential headers → `401`; an unknown authenticated path → `404` / `code` 5; and `/v1/portfolio/activities` → `200`. So signing is accepted and routing resolves; specific backends are down or unprovisioned. `/v1/portfolio/positions` returned `200` on 2026-08-30, so this is a CHANGE of state, not a standing condition. | true | Reproduced 5 independent rounds per path in one session. Needs a re-probe on another day to tell transient outage from a persistent per-account condition. |
| 2026-09-02 | `GET api /v1/orders` | n/a (account-scoped) | **CORRECTED 2026-09-02 -- the earlier reading of this row was WRONG and is retracted.** The probe sent `GET /v1/orders` and got `501` / grpc `code` 12 (UNIMPLEMENTED). That was read as 'the venue does not implement an order-history GET' and as evidence the SDK snapshot leads deployment. **Neither conclusion follows.** In the committed snapshot `/v1/orders` is the **POST create** path (`resources/orders.py` `create()` -> `self._client.post("/v1/orders")`); the order READ is `GET /v1/order/{id}` -- **singular** (`retrieve()`), and the open-orders list is `GET /v1/orders/open` (`list()`). A GET on a POST-only path returning UNIMPLEMENTED is the expected answer, not a finding. `GET /v1/order/{id}` was **never probed**, so whether an order read exists is UNKNOWN, and `POST /v1/orders` -- which R-7 needs -- is equally unprobed. L-11 binds venue gap claims exactly as it binds Nautilus ones: 'the venue does not implement its order endpoint' would kill R-7 outright and was asserted on evidence that does not support it. | true | The 501 itself reproduced 5x and is real; only the INTERPRETATION was wrong. Probing `GET /v1/order/{id}` needs a valid order id, which an empty account cannot supply. |
| 2026-09-02 | error taxonomy, `api.polymarket.us` private surface | n/a | **Authenticated-API error envelope is `google.rpc.Status`-shaped: `{code: int, message: str, details: list}`.** Observed HTTP-to-grpc pairs: `500`/13, `503`/14, `501`/12, `404`/5. `details` was `[]` in every case. `message` is the SAME generic string on all four codes ('The server was unable to process your request.'), so it carries ZERO discriminating information — classify on `code` and HTTP status only, never on message text. The unauthenticated `401` body is NOT JSON (33 bytes), so the JSON error envelope cannot be assumed on the auth-rejection path. | true | Reproduced across 4 distinct grpc codes and ~15 requests in one session. |
| 2026-09-02 | `GET gateway /v1/markets` | public listing | **G15 refutation re-confirmed on a second date**: the public gateway answered a non-browser client with `200` and a `{markets: [...]}` envelope, using a plain contact User-Agent. Public and private stacks fail independently — the gateway was healthy in the same minutes the private API was returning 500/503. | true | Reproduced on 2 distinct dates (2026-08-30, 2026-09-02). |
| 2026-09-02 | n/a | n/a | **UNRESOLVED — OQ-6: does an unfiltered `GET /v1/orders/open` return FOREIGN orders?** Unreachable today: the endpoint is implemented but returns `503` / `code` 14 on every attempt. It needs no code change to request — the repo's shape capturer takes the endpoint as a caller argument by design — so the only thing missing is a venue that answers. Re-probe when the private backend recovers. | true | 5 attempts, all `503`. |
| 2026-09-02 | n/a | n/a | **UNRESOLVED — the ±30 s timestamp window could not be re-tested**, and no clock-skew anomaly was observed: the host clock produced accepted signatures on the one private path that answered. No 429 and no rate limiting of any kind was encountered at ~1 request per 3 seconds. | true | Observational; ~15 requests total in the session. |

---

## References

- [Polymarket.us Docs](https://docs.polymarket.us/)
- [polymarket_us Python SDK](https://github.com/Polymarket/polymarket-us-python)
- [NWS API](https://api.weather.gov/) — see sibling skill `nws-cli-settlement` for settlement-grade product selection.
- Nautilus Trader extension points — see sibling skill `nautilus-trader-patterns`.
