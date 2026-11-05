# Kalshi history as a large-sample prior for K1 — 2026-09-02

Verdict: **YES, and it is the identical measurement on the identical settlement
source, not a loose proxy.** Verified empirically against the live public API,
unauthenticated, on 2026-09-02. Ordered by the operator's question: "can we
source that data somewhere else to speed up the go-live?"

## Why this is K1's question and not merely adjacent to it

K1 asks whether a cheap-ask daily-high bucket bought on D-1 settles YES more
often than break-even. Its two legs:

| Leg | Polymarket.us (our capture) | Kalshi (history) |
|---|---|---|
| Settlement truth | NWS CLI, stations NYC/MIA/MDW/LAX/SFO | NWS CLI, **the same five stations** — `CLINYC`, `CLIMIA`, `CLIMDW` (Midway, not O'Hare), `CLILAX`, `CLISFO`, from `rules_primary` |
| Ask at D-1 open | our tape, only for station-days captured before local midnight | candlesticks with **separate `yes_ask` / `yes_bid` / trade OHLC**; markets open **14:00Z on D-1** |
| Fee | `theta * C * p * (1-p)`, theta = 0.06 | `0.07 * C * p * (1-p)` taker — **identical functional form**, one constant differs |
| Qualifying observations | **8** in the largest cell (needs 96) | **~13,000** (order of magnitude; the cheap-ask fraction is from one sampled day) |

Real pull, `KXHIGHNY-26JUL02-B99.5`, D-1 opening hour: `yes_ask.close = 0.24`,
`yes_bid.close = 0.23`. Granularity 1 / 60 / 1440 min. Settled `result` field
gives ground truth directly.

## Access

- `GET https://api.elections.kalshi.com/trade-api/v2/historical/cutoff` → 200, no key.
- Historical candlesticks documented with an empty security array:
  https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- Overview: https://docs.kalshi.com/getting_started/historical_data
- Historical cutoff 2026-07-04; live endpoints cover the remainder.

## Coverage (full crawl of settled markets, five cities)

| Year | Markets | City-days | Buckets/day |
|---|---|---|---|
| 2021 | 386 | 279 | 1.4 |
| 2022 | 2,521 | 730 | 3.5 |
| 2023–26 | 26,496 | 4,408 | 6.0 |
| **Total** | **29,403** | **5,417** | |

Start dates: NY 2021-08-05, CHI 2021-08-18, MIA 2023-05-10, LAX 2025-01-04,
SFO 2026-01-13. Series: `KXHIGHNY`, `KXHIGHMIA`, `KXHIGHCHI`, `KXHIGHLAX`,
`KXHIGHTSFO` (SF is *not* `KXHIGHSF`). Tickers `SERIES-YYMMMDD-Bxx.x` (2-degree
between-buckets) and `-Txx` (tails).

## What it can and cannot say — binding caveats

1. **It is a prior for the FAMILY, not a measurement of Polymarket.us.** The
   settlement leg is identical; the ask leg is a different venue with different
   participants, liquidity and tick regime. A Kalshi base rate can tell us early
   whether the cheap-D-1 family is dead. It cannot estimate Polymarket.us's own
   rate, which K1 on our tape still has to measure ([[L-13]]: a statistic is not
   comparable across regimes it was not sampled from).
2. **Two regime breaks inside Kalshi's own history.** 2021–22 markets were
   single-threshold (1.4–3.5 per day), not exhaustive buckets. **Stratify by era**;
   a pooled rate mixes incomparable samples.
3. **No depth.** OHLC of top-of-book only, no size. Whether a cheap ask was
   fillable at size is UNVERIFIED — consistent with Polymarket.us, where the bid
   side is ~0.3 contracts.
4. Kalshi cites "The Weather Company" as the reader of the NWS CLI product — one
   extra hop versus Breezy's direct NWS path. Same underlying.
5. The maker constant 0.0175 is from a secondary source and UNVERIFIED; the taker
   0.07 is what K1's break-even needs and is the one to use.

## What this changes

The **family-viability** half of the K1 wait collapses from weeks to hours: port
K1's pre-registered methodology to Kalshi history and run it. The
**venue-specific** half does not: Polymarket.us's own rate is still gated on our
capture. And **neither half moves the mechanical go-live date**, which is gated
on the exec spine (R-6d → R-7), not on data.

## Companion finding, same day: Polymarket.us itself retains NO ask history

Checked empirically, GET-only, ~400 paced requests, no 429 — so the Kalshi
prior is the *only* external source, not merely the best one.

- **No retail price-history endpoint.** The whole retail market-data surface is
  six point-in-time paths (`/v1/markets`, `/market/id`, `/market/slug`,
  `/{slug}/book`, `/{slug}/bbo`, `/{slug}/settlement`). Fifteen speculative
  history-shaped GETs → 404. Candlestick/historical data exists only on the
  institutional Exchange (Private Key JWT, gRPC/FIX), unreachable with retail
  Ed25519 keys.
- **One undocumented route, `GET gateway /v1/price-history`, answers 400
  INVALID_ARGUMENT where near-miss paths 404** — the route exists, the
  arguments are rejected, ~45 GET shapes tried. Most likely a gRPC-gateway
  transcode wanting a POST body, which is outside the read-only allowlist and
  was deliberately not attempted. **UNRESOLVED**, and nothing about `.com`'s
  `/prices-history` transfers.
- **What resolved markets retain:** 3,683 climate markets over 123 station-days
  (2026-04-22 → 2026-09-03), queryable indefinitely, each carrying a single
  daily trade summary (`openPx/closePx/highPx/lowPx/lastTradePx`, `*SetTime`,
  `sharesTraded`, `settlementPx`). **One row per market, not a series**; no
  depth; `bids`/`offers` emptied at expiry; every quote-derived field null or
  dropped on resolution.
- **Why `openPx` is not ask-at-open.** It is trade-derived (absent exactly where
  `sharesTraded` is null, 105/105). `openSetTime` minus local-standard midnight
  ranged −11.0 h to +22.45 h, **median +13.1 h** — the modal first print lands
  mid-station-day, not the evening before. Only 59/128 printed pre-midnight.
  K1 specifies a resting offer with size; a print is a fill. Substituting is a
  unit change ([[native-substitution-is-a-unit-change]]), not a data source.
- **K1-qualifying asks recoverable from the venue: zero.** Cheap pre-midnight
  *prints* exist (central estimate ~150 over 123 days, UNVERIFIED from two
  samples, and liquidity ramped so the archive is non-uniform) but they are the
  wrong quantity.

**Net for the operator's question:** the family-viability prior comes from
Kalshi and can be had today; Polymarket.us's own rate comes from our recorder
and nowhere else. Discovery log appended, all rows `provisional: true`, at
`.claude/skills/polymarket-us-integration/SKILL.md`.
