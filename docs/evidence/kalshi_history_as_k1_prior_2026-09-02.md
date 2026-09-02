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
