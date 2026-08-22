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
- Query string is INCLUDED in the path.
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
| — | — | — | — | — | (empty; populated by discovery agent) |

---

## References

- [Polymarket.us Docs](https://docs.polymarket.us/)
- [polymarket_us Python SDK](https://github.com/Polymarket/polymarket-us-python)
- [NWS API](https://api.weather.gov/) — see sibling skill `nws-cli-settlement` for settlement-grade product selection.
- Nautilus Trader extension points — see sibling skill `nautilus-trader-patterns`.
