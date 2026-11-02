# P-0 candle semantics — 2026-11-02

Scope: committed fixture metadata and candles only; no outcome field inspected.
Network GET count: **0**; GET paths: none. No raw response or cache written.

## Fixture evidence

- `tests/fixtures/kalshi/candles_historical_modern.json`: `ticker` = `KXHIGHNY-26JUL02-T99`; `candlesticks[0].end_period_ts` = 1782918000 = 2026-07-01T15:00:00Z. Historical OHLC uses `yes_bid.close` (also `open`, `high`, `low`).
- Matching `tests/fixtures/kalshi/historical_markets_KXHIGHNY_modern.json`: `markets[].open_time` = 2026-07-01T14:00:00Z for that ticker; the candle end is open + 3600 s.
- `tests/fixtures/kalshi/candles_live_modern.json`: `ticker` = `KXHIGHNY-26SEP01-T90`; `candlesticks[0].end_period_ts` = 1788188400 = 2026-08-31T15:00:00Z. Live OHLC uses `yes_bid.close_dollars` (also `open_dollars`, `high_dollars`, `low_dollars`).
- Matching `tests/fixtures/kalshi/live_markets_KXHIGHNY.json`: `markets[].open_time` = 2026-08-31T14:00:00Z for that ticker; again end = open + 3600 s.
- `tests/fixtures/kalshi/market_KXHIGHLAX_2026-09-04.json`: the market opening field is `markets[].open_time`, an ISO-8601 UTC timestamp, 2026-09-04T14:00:00Z for all five listed markets. This is a separate market fixture, not a join to either NY candle.

## Finding and F-19 decision

Both schemas use `end_period_ts` to label the END of the hourly bucket (end−1 h, end], consistent with `plan_r2_delta.md` R2-1 and k1's first-hour request (`period_interval=60`, `start_ts=open_ts`, `end_ts=open_ts+3600`). The fixtures resolve END versus START labelling; they do not independently test tick inclusion exactly on a boundary.

F-19 decision: For hourly candles in both schemas, `end_period_ts` is the bucket END of (end−1 h, end]; market opening is `markets[].open_time`. Use the candle only when `end_period_ts == ref_end`, reading historical `yes_bid.close` or live `yes_bid.close_dollars` through `_candle_decimal`; no carry-forward. Mismatch found at S3b ⇒ HALT to peer loop, no verdict.
