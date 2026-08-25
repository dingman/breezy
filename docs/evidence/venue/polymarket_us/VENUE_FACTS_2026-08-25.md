# Polymarket.us Venue Facts - 2026-08-25

Investigation-only evidence capture for Breezy's Polymarket.us build blockers.
DIRECT EVIDENCE - capture method: all live venue probes cited here were
unauthenticated HTTP GET requests. No credentials were created, used, or
observed.

## Summary

| Question | One-line answer | Confidence |
|---|---|---|
| Q1 Fee schedule | The current Polymarket.us docs exactly state `Fee = Theta * C * p * (1 - p)`, taker theta `0.06`, maker rebate theta `-0.0125`, with taker volume rebates; live market metadata exposes `feeCoefficient: 0.06`. | DIRECT |
| Q2 Order book depth | Retail `/v1/markets/{slug}/book` is L2 aggregated depth; the observed open weather market had 12 bid levels and 14 offer levels. Individual levels have only `px` and `qty`, no per-level timestamps. | DIRECT |
| Q3 `settlementPx` semantics | `stats.settlementPx` is not a final-settlement oracle: an open market had `settlementPx`, while `/settlement` returned 404. A resolved book showed final-looking `settlementPx`, but `/settlement` also returned 404 for resolved weather buckets. | DIRECT plus UNRESOLVED |
| Q4 Slug immutability | Not proven immutable. Docs say slugs are used everywhere, but do not say immutable. Numeric `id` is documented as the unique market identifier. | UNRESOLVED |
| Q5 API key scoping | Retail docs do not document trade-only keys, withdrawal separation, IP allowlisting, or notional caps. Institutional docs do document scopes, including `write:orders` separate from `write:funding`. | UNRESOLVED for retail |
| Q6 `manualOrderIndicator` | Retail order docs define manual vs automatic; an autonomous trading system should send `MANUAL_ORDER_INDICATOR_AUTOMATIC` on retail. | DIRECT |
| Q7 Weather market structure | A weather series contains date events; each date event contains mutually-exclusive temperature buckets as separate yes/no markets. Current NYC high buckets have tick `0.01`, `minimumTradeQty: 0.01`, and decimal book quantities. | DIRECT |
| Q8 Settlement source | Weather docs and live market text name NWS Daily Climate Report / Climatological Report (Daily) and station mappings. Exact preliminary-vs-final and timezone/day-boundary semantics are not fully specified beyond the date and 8:00 AM ET settlement schedule. | DIRECT plus UNRESOLVED |
| Q9 Docs vs SDK casing | Current retail docs and live JSON agree with the SDK's camelCase schema. One fee-page note uses snake_case partner execution-report field names. | DIRECT |
| Q10 Retail vs institutional | Retail API exists for app/KYC users and is the documented individual-trader path. Institutional DMA is a separate onboarding, auth, host, rate-limit, scope, and protocol surface. Retail is available, but lacks documented server-side key safety controls. | DIRECT plus INFERENCE |

## Captured Evidence Inventory

DIRECT EVIDENCE - official docs snapshots:

- `docs/evidence/venue/polymarket_us/docs_snapshots/llms_2026-08-25.txt` from `https://docs.polymarket.us/llms.txt`
- `docs/evidence/venue/polymarket_us/docs_snapshots/fees_2026-08-25.md` from `https://docs.polymarket.us/fees.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/weather-faqs_2026-08-25.md` from `https://docs.polymarket.us/faqs/weather-faqs.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_authentication_2026-08-25.md` from `https://docs.polymarket.us/api-reference/authentication.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_rate-limits_2026-08-25.md` from `https://docs.polymarket.us/api-reference/rate-limits.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_overview_2026-08-25.md` from `https://docs.polymarket.us/api-reference/orders/overview.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_create-order_2026-08-25.md` from `https://docs.polymarket.us/api-reference/orders/create-order.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_markets_get-markets_2026-08-25.md` from `https://docs.polymarket.us/api-reference/markets/get-markets.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_markets_get-market-book_2026-08-25.md` from `https://docs.polymarket.us/api-reference/markets/get-market-book.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_markets_get-market-bbo_2026-08-25.md` from `https://docs.polymarket.us/api-reference/markets/get-market-bbo.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_markets_get-market-settlement_2026-08-25.md` from `https://docs.polymarket.us/api-reference/markets/get-market-settlement.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_events_get-events_2026-08-25.md` from `https://docs.polymarket.us/api-reference/events/get-events.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_websocket_markets_2026-08-25.md` from `https://docs.polymarket.us/api-reference/websocket/markets.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_overview_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/overview.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_onboarding_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/onboarding.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_authentication_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/authentication.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_environments_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/environments.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_rate-limits_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/rate-limits.md`
- `docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_market-data_2026-08-25.md` from `https://docs.polymarket.us/trader-guide/market-data.md`

DIRECT EVIDENCE - SDK source snapshot:

- `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/`

DIRECT EVIDENCE - raw live JSON captures:

- `docs/evidence/venue/polymarket_us/raw/series_limit100.json`
- `docs/evidence/venue/polymarket_us/raw/series_weather_query.json`
- `docs/evidence/venue/polymarket_us/raw/series_id_35.json`
- `docs/evidence/venue/polymarket_us/raw/events_seriesId_35.json`
- `docs/evidence/venue/polymarket_us/raw/events_seriesId_35_active.json`
- `docs/evidence/venue/polymarket_us/raw/events_seriesId_36_active.json`
- `docs/evidence/venue/polymarket_us/raw/search_weather.json`
- `docs/evidence/venue/polymarket_us/raw/search_weather_seriesIds_35.json`
- `docs/evidence/venue/polymarket_us/raw/market_open_510636_by_id.json`
- `docs/evidence/venue/polymarket_us/raw/market_open_510636_by_slug.json`
- `docs/evidence/venue/polymarket_us/raw/book_open_510636.json`
- `docs/evidence/venue/polymarket_us/raw/bbo_open_510636.json`
- `docs/evidence/venue/polymarket_us/raw/settlement_open_510636.json`
- `docs/evidence/venue/polymarket_us/raw/settlement_open_510636_fromEp3.json`
- `docs/evidence/venue/polymarket_us/raw/market_closed_15806_by_id.json`
- `docs/evidence/venue/polymarket_us/raw/market_closed_15806_by_slug.json`
- `docs/evidence/venue/polymarket_us/raw/book_closed_15806.json`
- `docs/evidence/venue/polymarket_us/raw/bbo_closed_15806.json`
- `docs/evidence/venue/polymarket_us/raw/settlement_closed_15806.json`
- `docs/evidence/venue/polymarket_us/raw/settlement_closed_15806_fromEp3.json`
- `docs/evidence/venue/polymarket_us/raw/book_closed_15389.json`
- `docs/evidence/venue/polymarket_us/raw/settlement_closed_15389_fromEp3.json`
- `docs/evidence/venue/polymarket_us/raw/markets_categories_climate.json`
- `docs/evidence/venue/polymarket_us/raw/markets_slug_open.json`
- `docs/evidence/venue/polymarket_us/raw/markets_tagIds_weather.json`

## Q1. Fee Schedule

ANSWER: DIRECT EVIDENCE. Polymarket.us currently documents the same theta formula
Breezy had assumed, but this investigation now has a Polymarket.us source for it:
taker theta `0.06`, maker rebate theta `-0.0125`, probability-weighted by
`p * (1 - p)` and contract count `C`. Fees are only on executions, not canceled
or rejected orders. Public weather market metadata also exposes
`feeCoefficient: 0.06`. Authenticated fill payloads were not observed because
credentials are prohibited.

DIRECT EVIDENCE - `https://docs.polymarket.us/fees.md`, captured in
`docs_snapshots/fees_2026-08-25.md`:

```text
Fees are computed using a symmetric formula that scales with price uncertainty:

Fee = Θ × C × p × (1 - p)

Where:

* C is the number of contracts
* p is the trade price ($0.01 to $0.99)
* Θ (theta) is the fee coefficient
```

DIRECT EVIDENCE - same page:

```text
|                  | Theta   | Max (p = $0.50) |
| ---------------- | ------- | ---------------- |
| Taker Fee        | 0.06    | $1.50            |
| Maker Rebate     | -0.0125 | -$0.31           |
```

DIRECT EVIDENCE - same page:

```text
* Maker rebate is applied at the point of trade.
* Taker rebate: Participants who trade over $250,000 in taker volume during the prior calendar month receive rebates according to the following schedule.
```

DIRECT EVIDENCE - same page:

```text
API integrators: C is the number of contracts and p the decimal price. Execution reports carry these as fixed-point integers, and the collected fee in scaled notional units
```

DIRECT EVIDENCE - same page:

```text
* All fees and rebates are rounded to the nearest $0.01 using banker's rounding (round half to even).
* When an aggressive order fills against multiple resting orders, each fill is charged its banker's-rounded fee
```

DIRECT EVIDENCE - same page:

```text
Yes. Taker fees are deducted from your balance at the time of the trade. Maker rebates are credited to your balance at the time of the fill.
```

DIRECT EVIDENCE - same page:

```text
No. Fees are only charged when a trade executes. If your order is canceled, expires, or is rejected, no fee is charged.
```

DIRECT EVIDENCE - live `GET https://gateway.polymarket.us/v1/market/id/510636`,
captured in `raw/market_open_510636_by_id.json`:

```json
{
  "id": "510636",
  "slug": "tc-temp-nychigh-2026-08-25-lt79f",
  "status": "MARKET_STATUS_OPEN",
  "feeCoefficient": 0.06,
  "minimumTradeQty": 0.01
}
```

DIRECT EVIDENCE - SDK source `sdk_snapshot/polymarket_us_0.1.2/types/orders.py`
contains authenticated response fields but no fee formula:

```text
commissionNotionalTotalCollected
commissionsBasisPoints
makerCommissionsBasisPoints
commissionNotionalCollected
```

INFERENCE: the prior `.com` carry-over was a process defect even though the
numeric taker/maker rates now match the Polymarket.us fee page. The build plan
should cite the `.us` fee page and live `feeCoefficient` field, not `.com`.

## Q2. Order Book Depth

ANSWER: DIRECT EVIDENCE. Retail `/v1/markets/{slug}/book` returns L2 aggregated
multi-level depth, not only top-of-book. Individual levels do not carry
timestamps; each level has `px` and `qty`. The response has a single
`transactTime` and stat-level timestamps. Retail also has `/bbo` and market-data
WebSocket subscriptions, but no separate retail "depth" endpoint was found
beyond `/book`. Institutional has a separate `/v1/orderbook/{symbol}` endpoint,
but that is a different API surface.

DIRECT EVIDENCE - docs for
`GET https://gateway.polymarket.us/v1/markets/{slug}/book`, captured in
`docs_snapshots/api-reference_markets_get-market-book_2026-08-25.md`:

```text
Retrieve current market data (order book, stats) for a specific market by its slug
```

DIRECT EVIDENCE - same docs define:

```text
marketSlug
bids
offers
state
stats
transactTime
```

DIRECT EVIDENCE - same docs define each book entry as:

```text
px
qty
```

DIRECT EVIDENCE - live
`GET https://gateway.polymarket.us/v1/markets/tc-temp-nychigh-2026-08-25-lt79f/book`,
captured in `raw/book_open_510636.json`, contained 12 bid levels and 14 offer
levels. Excerpt:

```json
{
  "marketData": {
    "marketSlug": "tc-temp-nychigh-2026-08-25-lt79f",
    "bids": [
      {"px": {"value": "0.5300", "currency": "USD"}, "qty": "123.4800"},
      {"px": {"value": "0.5200", "currency": "USD"}, "qty": "56.0000"},
      {"px": {"value": "0.5100", "currency": "USD"}, "qty": "10089.2100"}
    ],
    "offers": [
      {"px": {"value": "0.5400", "currency": "USD"}, "qty": "4.0000"},
      {"px": {"value": "0.5500", "currency": "USD"}, "qty": "158.0000"},
      {"px": {"value": "0.5600", "currency": "USD"}, "qty": "35.0000"}
    ],
    "transactTime": "2026-08-25T00:19:48.120237895Z"
  }
}
```

DIRECT EVIDENCE - live
`GET https://gateway.polymarket.us/v1/markets/tc-temp-nychigh-2026-08-25-lt79f/bbo`,
captured in `raw/bbo_open_510636.json`, is top-of-book plus depth counts:

```json
{
  "bestAsk": {"value": "0.5400", "currency": "USD"},
  "bestBid": {"value": "0.5300", "currency": "USD"},
  "askDepth": 14,
  "bidDepth": 12
}
```

DIRECT EVIDENCE - `https://docs.polymarket.us/api-reference/websocket/markets.md`,
captured in `docs_snapshots/api-reference_websocket_markets_2026-08-25.md`:

```text
| SUBSCRIPTION_TYPE_MARKET_DATA      | Full order book and market stats |
| SUBSCRIPTION_TYPE_MARKET_DATA_LITE | Lightweight price data only      |
```

DIRECT EVIDENCE - institutional docs for
`https://docs.polymarket.us/api-reference/order-book/get-order-book.md` describe
a different host/API path:

```text
get /v1/orderbook/{symbol}
```

## Q3. `settlementPx` Semantics

ANSWER: DIRECT EVIDENCE plus UNRESOLVED. `stats.settlementPx` is not final-only:
an open market returned `settlementPx: 0.4900` while the dedicated settlement
endpoint for the same slug returned 404 "Settlement not found". A resolved
weather market book returned `settlementPx: 1.0000` and
`MARKET_STATE_EXPIRED`, but `/settlement` still returned 404 for that resolved
weather slug, including with `fromEp3=true`. Therefore Breezy must not treat
book `settlementPx` as final payout without additional finality checks.

DIRECT EVIDENCE - live open book
`GET https://gateway.polymarket.us/v1/markets/tc-temp-nychigh-2026-08-25-lt79f/book`,
captured in `raw/book_open_510636.json`:

```json
{
  "state": "MARKET_STATE_OPEN",
  "stats": {
    "lastTradePx": {"value": "0.5300", "currency": "USD"},
    "settlementPx": {"value": "0.4900", "currency": "USD"},
    "settlementSetTime": "2026-08-24T21:00:03.916809272Z",
    "settlementPriceCalculationMethod": "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2",
    "currentPx": {"value": "0.5300", "currency": "USD"}
  }
}
```

DIRECT EVIDENCE - live open settlement endpoint
`GET https://gateway.polymarket.us/v1/markets/tc-temp-nychigh-2026-08-25-lt79f/settlement`,
captured in `raw/settlement_open_510636.json`, returned HTTP 404:

```json
{
  "code": 5,
  "message": "Settlement not found for market tc-temp-nychigh-2026-08-25-lt79f",
  "details": []
}
```

DIRECT EVIDENCE - live resolved market
`GET https://gateway.polymarket.us/v1/market/id/15806`, captured in
`raw/market_closed_15806_by_id.json`:

```json
{
  "id": "15806",
  "slug": "tc-temp-nychigh-2026-04-23-gte72lt73f",
  "active": false,
  "closed": true,
  "status": "MARKET_STATUS_RESOLVED",
  "outcomePrices": "[\"1\",\"0\"]"
}
```

DIRECT EVIDENCE - live resolved book
`GET https://gateway.polymarket.us/v1/markets/tc-temp-nychigh-2026-04-23-gte72lt73f/book`,
captured in `raw/book_closed_15806.json`:

```json
{
  "state": "MARKET_STATE_EXPIRED",
  "stats": {
    "settlementPx": {"value": "1.0000", "currency": "USD"},
    "settlementSetTime": "2026-04-24T12:00:53.061167120Z",
    "settlementPriceCalculationMethod": "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1",
    "currentPx": {"value": "1.0000", "currency": "USD"}
  }
}
```

DIRECT EVIDENCE - same resolved slug settlement endpoint returned HTTP 404,
captured in `raw/settlement_closed_15806.json` and
`raw/settlement_closed_15806_fromEp3.json`:

```json
{
  "code": 5,
  "message": "Settlement not found for market tc-temp-nychigh-2026-04-23-gte72lt73f",
  "details": []
}
```

UNRESOLVED: this single-time capture proves `settlementPx` can exist pre-final,
but does not prove how often it updates. Proving "continuously updated" would
require a longitudinal unauthenticated polling capture or official venue answer.
The dedicated `/settlement` endpoint also appears unusable for the weather
resolved buckets tested here; a venue support answer or broader settlement
fixture is needed before relying on it.

## Q4. Slug Immutability

ANSWER: UNRESOLVED. Current docs and SDK establish that slugs are central API
identifiers, but do not prove that `marketSlug` is immutable for a market's
lifetime. The stable identifier directly documented as unique is numeric/string
market `id`.

DIRECT EVIDENCE - `https://docs.polymarket.us/concepts/events-and-markets.md`,
captured in `docs_snapshots/concepts_events-and-markets_2026-08-25.md`:

```text
Every market has a slug - a URL-friendly identifier like aec-nfl-kc-phi-2026-02-09. This is what you use everywhere: placing orders, fetching order books, subscribing to WebSocket streams.
```

DIRECT EVIDENCE - `https://docs.polymarket.us/api-reference/markets/get-markets.md`,
captured in `docs_snapshots/api-reference_markets_get-markets_2026-08-25.md`,
describes:

```text
id:
  description: Unique market identifier
slug:
  description: Market slug for URL
```

DIRECT EVIDENCE - live market-by-id and market-by-slug for the same open market,
captured in `raw/market_open_510636_by_id.json` and
`raw/market_open_510636_by_slug.json`, returned the same pair:

```json
{
  "id": "510636",
  "slug": "tc-temp-nychigh-2026-08-25-lt79f",
  "updatedAt": "2026-08-25T00:17:58Z"
}
```

DIRECT EVIDENCE - SDK source
`sdk_snapshot/polymarket_us_0.1.2/resources/markets.py` exposes both lookup
paths:

```text
/v1/market/id/{id}
/v1/market/slug/{slug}
```

UNRESOLVED: neither docs nor SDK say the slug cannot change. What would unblock
this: official venue statement that market slugs are immutable, or a
longitudinal fixture proving the same numeric market `id` keeps the same `slug`
through open, close, and settlement. Until then, persist numeric `id` as the
stable venue identifier and treat slug as routing/display metadata.

## Q5. API Key Scoping

ANSWER: UNRESOLVED for retail. Retail docs describe creating a key ID and secret
key after app signup and identity verification, plus revocation guidance, but do
not document trade-only keys, withdrawal-disabled keys, IP allowlisting, or
server-side spending/notional caps. Institutional docs do document OAuth scopes,
including `write:orders` separate from `write:funding`, but that does not prove
the same controls exist for retail keys.

DIRECT EVIDENCE - retail authentication docs
`https://docs.polymarket.us/api-reference/authentication.md`, captured in
`docs_snapshots/api-reference_authentication_2026-08-25.md`:

```text
Authenticated endpoints - trading, portfolio, and WebSocket - require an API key. Public endpoints like market data and events don't need one.
```

DIRECT EVIDENCE - same page:

```text
Create an API key - Click to create a new key. You'll get a Key ID and a Secret Key.
```

DIRECT EVIDENCE - same page:

```text
Your secret key is shown only once. Copy it somewhere safe before closing the dialog.
```

DIRECT EVIDENCE - same page:

```text
Revoke compromised keys immediately at polymarket.us/developer
```

DIRECT EVIDENCE - retail rate-limit docs
`https://docs.polymarket.us/api-reference/rate-limits.md`, captured in
`docs_snapshots/api-reference_rate-limits_2026-08-25.md`:

```text
The Retail API enforces a global rate limit of 20 requests per second per API key across all endpoints.
```

DIRECT EVIDENCE - institutional authentication docs
`https://docs.polymarket.us/trader-guide/authentication.md`, captured in
`docs_snapshots/trader-guide_authentication_2026-08-25.md`:

```text
Your application is granted specific scopes that control which API endpoints you can access. Scopes are included in your access token and validated by the API.
```

DIRECT EVIDENCE - same institutional page:

```text
| write:orders  | Insert / cancel / replace / modify orders; create combo instruments and manage RFQs and quotes |
| write:funding | Update funding, create deposits and withdrawals                                               |
```

UNRESOLVED: retail server-side safety controls may exist in the post-auth
developer portal, but this task prohibited signup/authentication/KYC. What would
unblock this: a redacted operator portal screenshot, an official support answer,
or docs that explicitly describe retail key scopes, IP allowlists, and spending
caps.

## Q6. `manualOrderIndicator`

ANSWER: DIRECT EVIDENCE. For the retail API, valid values are
`MANUAL_ORDER_INDICATOR_MANUAL` and `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
For Breezy's autonomous trading system on the retail API, the correct value is
`MANUAL_ORDER_INDICATOR_AUTOMATIC`.

DIRECT EVIDENCE - retail order overview
`https://docs.polymarket.us/api-reference/orders/overview.md`, captured in
`docs_snapshots/api-reference_orders_overview_2026-08-25.md`:

```text
Required to indicate whether the order is placed by a human or automated system:

| Value                              | Description                                 |
| ---------------------------------- | ------------------------------------------- |
| MANUAL_ORDER_INDICATOR_MANUAL      | Order placed manually by a user             |
| MANUAL_ORDER_INDICATOR_AUTOMATIC   | Order placed by an automated trading system |
```

DIRECT EVIDENCE - retail create-order schema
`https://docs.polymarket.us/api-reference/orders/create-order.md`, captured in
`docs_snapshots/api-reference_orders_create-order_2026-08-25.md`:

```text
manualOrderIndicator:
  description: Indicates whether the order was placed manually or automatically
```

DIRECT EVIDENCE - same create-order schema:

```text
ManualOrderIndicator:
  enum:
    - MANUAL_ORDER_INDICATOR_MANUAL
    - MANUAL_ORDER_INDICATOR_AUTOMATIC
  description: Indicates whether the order was placed manually by a user or automatically by a trading system
```

DIRECT EVIDENCE - SDK source
`sdk_snapshot/polymarket_us_0.1.2/types/orders.py` matches retail docs:

```python
ManualOrderIndicator = Literal[
    "MANUAL_ORDER_INDICATOR_MANUAL",
    "MANUAL_ORDER_INDICATOR_AUTOMATIC",
]
```

DIRECT EVIDENCE - institutional insert-order docs use a different enum spelling,
captured in `docs_snapshots/api-reference_trading_insert-order_2026-08-25.md`:

```text
- MANUAL_ORDER_INDICATOR_MANUAL
- MANUAL_ORDER_INDICATOR_AUTOMATED
```

INFERENCE: because the operator decision is retail, Breezy should use
`MANUAL_ORDER_INDICATOR_AUTOMATIC`, not the institutional-only
`MANUAL_ORDER_INDICATOR_AUTOMATED` spelling.

## Q7. Weather Market Structure

ANSWER: DIRECT EVIDENCE. The working traversal for weather is via events using
`seriesId`, for example `GET /v1/events?seriesId=35`. A daily high city series
contains date events; each date event contains separate mutually-exclusive
temperature-bucket markets, and each bucket market has two sides, Yes and No.
For the current NYC high market captured here, tick size is `0.01`,
`minimumTradeQty` is `0.01`, and live book quantities are decimal strings. This
conflicts with the public "Fractional Contracts" learn page, which says only
whole contracts are supported.

DIRECT EVIDENCE - live
`GET https://gateway.polymarket.us/v1/series?limit=100`, captured in
`raw/series_limit100.json`, includes:

```json
[
  {"id": "35", "slug": "weather-daily-high-nyc", "title": "Weather Daily High NYC"},
  {"id": "36", "slug": "weather-daily-low-nyc", "title": "Weather Daily Low NYC"},
  {"id": "37", "slug": "weather-daily-high-miami", "title": "Weather Daily High Miami"},
  {"id": "38", "slug": "weather-daily-low-miami", "title": "Weather Daily Low Miami"},
  {"id": "39", "slug": "weather-daily-high-chicago", "title": "Weather Daily High Chicago"},
  {"id": "40", "slug": "weather-daily-low-chicago", "title": "Weather Daily Low Chicago"},
  {"id": "41", "slug": "weather-daily-high-los-angeles", "title": "Weather Daily High Los Angeles"},
  {"id": "42", "slug": "weather-daily-low-los-angeles", "title": "Weather Daily Low Los Angeles"},
  {"id": "43", "slug": "weather-daily-high-san-francisco", "title": "Weather Daily High San Francisco"},
  {"id": "44", "slug": "weather-daily-low-san-francisco", "title": "Weather Daily Low San Francisco"}
]
```

DIRECT EVIDENCE - events docs
`https://docs.polymarket.us/api-reference/events/get-events.md`, captured in
`docs_snapshots/api-reference_events_get-events_2026-08-25.md`, documents the
filter:

```text
seriesId
description: Filter by series IDs
```

DIRECT EVIDENCE - live
`GET https://gateway.polymarket.us/v1/events?limit=20&seriesId=35&active=true&closed=false`,
captured in `raw/events_seriesId_35_active.json`, returned two active NYC high
events:

```json
{
  "events": [
    {
      "id": "89696",
      "slug": "temp-nychigh-2026-08-24",
      "seriesSlug": "weather-daily-high-nyc",
      "market_count": 6
    },
    {
      "id": "90791",
      "slug": "temp-nychigh-2026-08-25",
      "seriesSlug": "weather-daily-high-nyc",
      "market_count": 6
    }
  ]
}
```

DIRECT EVIDENCE - the 2026-08-25 NYC high event in
`raw/events_seriesId_35_active.json` contains these six separate bucket markets:

| Market id | Slug | Title | Description bound excerpt |
|---|---|---|---|
| 510636 | `tc-temp-nychigh-2026-08-25-lt79f` | `78 or below` | `less than or equal to 78F` |
| 510637 | `tc-temp-nychigh-2026-08-25-gte79lt80f` | `79 to 80` | `between 79F and 80F` |
| 510638 | `tc-temp-nychigh-2026-08-25-gte81lt82f` | `81 to 82` | `between 81F and 82F` |
| 510639 | `tc-temp-nychigh-2026-08-25-gte83lt84f` | `83 to 84` | `between 83F and 84F` |
| 510640 | `tc-temp-nychigh-2026-08-25-gte85lt86f` | `85 to 86` | `between 85F and 86F` |
| 510641 | `tc-temp-nychigh-2026-08-25-gte87f` | `87 or above` | `greater than or equal to 87F` |

DIRECT EVIDENCE - each bucket market has Yes/No sides. Excerpt for market
`510636`, captured in `raw/market_open_510636_by_id.json`:

```json
{
  "marketSides": [
    {
      "id": "1020784",
      "description": "Yes",
      "marketId": 510636,
      "long": true,
      "quote": {"value": "0.5400", "currency": "USD"},
      "tradable": true
    },
    {
      "id": "1020785",
      "description": "No",
      "marketId": 510636,
      "long": false,
      "quote": {"value": "0.47", "currency": "USD"},
      "tradable": true
    }
  ]
}
```

DIRECT EVIDENCE - market fields for `510636`, same raw capture:

```json
{
  "orderPriceMinTickSize": 0.01,
  "minimumTradeQty": 0.01,
  "feeCoefficient": 0.06
}
```

DIRECT EVIDENCE - live book quantities are decimal strings, captured in
`raw/book_open_510636.json`:

```json
{"px": {"value": "0.5300", "currency": "USD"}, "qty": "123.4800"}
```

DIRECT EVIDENCE - retail orders docs
`https://docs.polymarket.us/api-reference/orders/overview.md`, captured in
`docs_snapshots/api-reference_orders_overview_2026-08-25.md`:

```text
minimumTradeQty | Smallest valid quantity, expressed in contracts. A value of 0.01 means 1% of a contract.
```

DIRECT EVIDENCE - same page:

```text
The quantity field on order requests and order responses is a number and can contain decimals for partial-contract markets.
```

DIRECT EVIDENCE - create-order docs
`https://docs.polymarket.us/api-reference/orders/create-order.md`, captured in
`docs_snapshots/api-reference_orders_create-order_2026-08-25.md`:

```text
Order quantity in contracts. Supports decimal quantities on markets whose minimumTradeQty is less than 1.
```

DIRECT EVIDENCE - contradictory learn page
`https://docs.polymarket.us/learn/trading/basics/fractional-shares.md`, captured
in `docs_snapshots/learn_trading_basics_fractional-shares_2026-08-25.md`:

```text
Polymarket US does not support fractional contracts. All trades are executed in whole event contracts.
```

DIRECT EVIDENCE - `GET https://gateway.polymarket.us/v1/markets?limit=20&categories=climate`,
captured in `raw/markets_categories_climate.json`, returned climate/weather
bucket markets. The correct plural `categories=climate` works for markets;
the prior `category=` parameter is not the documented parameter.

DIRECT EVIDENCE - `GET https://gateway.polymarket.us/v1/markets?limit=10&slug=tc-temp-nychigh-2026-08-25-lt79f`,
captured in `raw/markets_slug_open.json`, returned exactly one matching market.

INFERENCE: bucket bounds must be read from market title/description or explicit
fields if the venue later provides them. Do not derive bounds solely from slug
tokens; for example, the slug fragment `gte79lt80f` is paired with a title and
description saying `79 to 80` / `between 79F and 80F`.

## Q8. Settlement Source

ANSWER: DIRECT EVIDENCE plus UNRESOLVED. Official weather docs say settlement is
based on the official NWS Daily Climate Report (CLI) from the local Weather
Forecast Office, and list the current city station/product mappings. Live market
descriptions for current weather markets also name station and NWS
Climatological Report (Daily). The docs captured here do not fully specify
whether the preliminary or final CLI controls, nor the exact timezone/day
boundary beyond each contract's specified date and the stated 8:00 AM ET
settlement schedule.

DIRECT EVIDENCE - `https://docs.polymarket.us/faqs/weather-faqs.md`, captured in
`docs_snapshots/weather-faqs_2026-08-25.md`:

```text
Settlement is determined by the official NWS Daily Climate Report (CLI) published by the local Weather Forecast Office. The CLI is an official government record that reports observed high, low, and average temperatures for a given location and date.
```

DIRECT EVIDENCE - same weather FAQ:

```text
| City          | Station                                    | CLI Source |
| New York City | KNYC (Central Park)                        | CLINYC     |
| San Francisco | KSFO (San Francisco International Airport) | CLISFO     |
| Miami         | KMIA (Miami International Airport)         | CLIMIA     |
| Chicago       | KMDW (Chicago Midway Airport)              | CLIMDW     |
| Los Angeles   | KLAX (Los Angeles International Airport)   | CLILAX     |
```

DIRECT EVIDENCE - same weather FAQ:

```text
Settlement occurs at 8:00 AM ET on the day following the Contract's specified date. If the CLI reading is inconsistent with the 24-hour METAR observation for the same location, settlement may be delayed until 11:00 AM ET for review. If no data is published within one week of the scheduled release, the Contract settles at last fair market prices.
```

DIRECT EVIDENCE - live market object
`GET https://gateway.polymarket.us/v1/market/id/510636`, captured in
`raw/market_open_510636_by_id.json`:

```text
Will the highest temperature recorded at Central Park (KNYC) in New York City for 2026-08-25 as reported by the National Weather Service's Climatological Report (Daily) be less than or equal to 78F? Outcome verified from NWS Climatological Report.
```

DIRECT EVIDENCE - same raw market object:

```json
{
  "startDate": "2026-08-24T09:45:21Z",
  "gameStartTime": "2026-08-25T05:00:00Z",
  "endDate": "2026-08-26T05:00:00Z",
  "resolutionSource": null
}
```

UNRESOLVED: the docs and market object do not explicitly say "FINAL CLI" or
"PRELIMINARY CLI", and they do not fully define the timezone/day boundary in a
machine-actionable way. What would unblock this: official venue clarification,
or a large resolved-market alignment study comparing market settlement to
preliminary/final NWS CLI and 24-hour METAR observations.

## Q9. Docs vs SDK Casing

ANSWER: DIRECT EVIDENCE. The current retail REST and WebSocket docs agree with
the SDK's camelCase schema. Live JSON also uses camelCase. One fee-page note uses
snake_case field names for partner/execution-report decoding; that should not be
treated as the retail REST casing contract.

DIRECT EVIDENCE - SDK source
`sdk_snapshot/polymarket_us_0.1.2/types/orders.py`:

```python
marketSlug: str
manualOrderIndicator: ManualOrderIndicator
```

DIRECT EVIDENCE - SDK source
`sdk_snapshot/polymarket_us_0.1.2/websocket/types.py`:

```python
marketSlugs: list[str]
marketSlug: str
```

DIRECT EVIDENCE - retail order docs
`https://docs.polymarket.us/api-reference/orders/overview.md`:

```json
{
  "marketSlug": "your-market-slug",
  "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_MANUAL"
}
```

DIRECT EVIDENCE - retail WebSocket docs
`https://docs.polymarket.us/api-reference/websocket/markets.md`:

```json
{
  "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
  "marketSlugs": ["market-slug-1", "market-slug-2"]
}
```

DIRECT EVIDENCE - live market JSON in `raw/market_open_510636_by_id.json`:

```json
{
  "orderPriceMinTickSize": 0.01,
  "minimumTradeQty": 0.01,
  "bestBidQuote": {"value": "0.5300", "currency": "USD"}
}
```

DIRECT EVIDENCE - fee docs contain one snake_case note:

```text
commission_notional_collected
price_scale
fractional_quantity_scale
```

INFERENCE: update prior plan text that says current retail docs show snake_case;
as of the 2026-08-25 captures, retail docs and live JSON are camelCase.

## Q10. Retail vs Institutional

ANSWER: DIRECT EVIDENCE plus INFERENCE. Polymarket.us currently documents two
distinct API surfaces. Retail uses `gateway.polymarket.us` for public market
data and `api.polymarket.us` with Ed25519 `X-PM-*` headers for authenticated
trading. Institutional DMA uses `api.prod.polymarketexchange.com` /
`api.preprod.polymarketexchange.com`, Auth0 Private Key JWT, access tokens,
`x-participant-id`, scopes, and optional gRPC/FIX. Retail is documented as
available to individual traders after app signup, identity verification, and
developer portal key creation. It is an appropriate target for an individual
operator only if the missing retail server-side key controls in Q5 are accepted
or resolved.

DIRECT EVIDENCE - retail API intro
`https://docs.polymarket.us/api-reference/introduction.md`, captured in
`docs_snapshots/api-reference_introduction_2026-08-25.md`:

```text
The Polymarket US API is split into two parts: an authenticated API for trading and a public API for reading market data.
```

DIRECT EVIDENCE - same retail intro:

```text
https://api.polymarket.us
```

DIRECT EVIDENCE - same retail intro:

```text
https://gateway.polymarket.us
```

DIRECT EVIDENCE - same retail intro:

```text
Use the public API to browse what's available on Polymarket US. No API key needed.
```

DIRECT EVIDENCE - retail authentication docs
`https://docs.polymarket.us/api-reference/authentication.md`:

```text
Download the app
Complete identity verification
Go to the developer portal
Create an API key
```

DIRECT EVIDENCE - same retail authentication docs:

```text
X-PM-Access-Key
X-PM-Timestamp
X-PM-Signature
```

DIRECT EVIDENCE - same page:

```text
The signature is built by combining the timestamp, HTTP method, and path, then signing it with your secret key. Timestamps must be within 30 seconds of server time.
```

DIRECT EVIDENCE - retail rate-limit docs:

```text
The Retail API enforces a global rate limit of 20 requests per second per API key across all endpoints.
```

DIRECT EVIDENCE - retail rate-limit docs for automated systems:

```text
If you're running an automated trading system and need higher limits for production:
1. Document your use case and expected request volume
2. Email support@polymarket.us
3. Include which endpoints you need higher limits for
```

DIRECT EVIDENCE - institutional overview
`https://docs.polymarket.us/trader-guide/overview.md`, captured in
`docs_snapshots/trader-guide_overview_2026-08-25.md`:

```text
The Trader Guide is designed for:
* Institutional traders accessing markets directly
* Proprietary trading firms executing strategies programmatically
* Market makers providing liquidity
* Quantitative traders building automated trading systems
```

DIRECT EVIDENCE - institutional onboarding
`https://docs.polymarket.us/trader-guide/onboarding.md`:

```text
Individual traders: You do not need to complete this onboarding process. Head to the Retail Trading tab to get started.
```

DIRECT EVIDENCE - same institutional onboarding page:

```text
Create your account through the Polymarket Institutional registration portal
```

DIRECT EVIDENCE - institutional environments docs
`https://docs.polymarket.us/trader-guide/environments.md`:

```text
| Preprod | Pre-production validation | https://api.preprod.polymarketexchange.com | grpc-preprod.polymarketexchange.com:443 | pmx-preprod.us.auth0.com |
| Prod    | Production trading        | https://api.prod.polymarketexchange.com    | grpc-prod.polymarketexchange.com:443    | pmx-prod.us.auth0.com    |
```

DIRECT EVIDENCE - institutional authentication docs
`https://docs.polymarket.us/trader-guide/authentication.md`:

```text
The Polymarket Exchange API uses Private Key JWT authentication with RSA keys. You sign a JWT with your RSA private key and exchange it for an access token.
```

DIRECT EVIDENCE - same institutional page:

```text
Include the access token in the Authorization header for all API requests. For account-scoped endpoints (trading, positions, reports), you must also include the x-participant-id header.
```

DIRECT EVIDENCE - institutional market data docs
`https://docs.polymarket.us/trader-guide/market-data.md`:

```text
Price levels available: Multiple levels of depth (configurable), best bid/offer always included, deeper book available with appropriate scopes.
```

DIRECT EVIDENCE - institutional authentication scope table includes:

```text
read:l2marketdata | L2 orderbook depth (premium)
write:orders      | Insert / cancel / replace / modify orders
write:funding     | Update funding, create deposits and withdrawals
```

DIRECT EVIDENCE - institutional rate-limit docs
`https://docs.polymarket.us/trader-guide/rate-limits.md`:

```text
REST API traffic is subject to a firm-wide cap of 100 requests per second per firm
```

DIRECT EVIDENCE - same institutional rate-limit docs:

```text
GetOrderBook | 12 req/min | Prefer streaming for real-time data
GetBBO       | 12 req/min | Prefer streaming for real-time data
```

INFERENCE: retail is the right first implementation target for the current
operator decision only if Breezy accepts retail's weaker documented server-side
controls and lower per-key rate limit. If the operator requires scoped
trade-only/non-funding credentials, premium L2 market data entitlements, gRPC,
FIX, or firm-level controls, the current docs point to institutional onboarding,
not retail.
