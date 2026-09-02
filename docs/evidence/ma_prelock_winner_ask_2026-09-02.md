# M_A -- pre-lock winner-ask afternoon measurement

Generated 2026-09-02T22:16:51+00:00 from
`scripts/analysis/ma_prelock_winner_ask_study.py`. Spec: 
`docs/evidence/grok_no_edge_verdict_2026-09-02.md` SS2 / SS3 K-A, K-depth.

A descriptive join, not a backtest: no order, fill, position, fee or P&L appears anywhere in this pipeline. NautilusTrader is the exclusive owner of backtesting and execution.

## Tape integrity (LESSONS L-8) -- verified before interpretation

> breezy-quote-tape-preflight over /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us: all 989 staged files carrying M_A's target station-day instruments are INTACT -- 1252168 rows, 0 truncated, 0 unreadable, 0 empty.

Depth catalog: `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`
ASOS archive cache: `/home/jon/.local/share/breezy/archive/settlement-alignment-cache`

## IEM ASOS fetch

fetched 2026-08-30..2026-09-01 for SFO, MIA, MDW, LAX; see the run log for per-site outcomes.

## Per-station-day summary

| station | day | status | winner | coverage (min) | afternoon snapshots | qualifying cells | min ask | size@min | first vanish (LST) | first >=0.99 (LST) |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| LAX | 2026-08-31 | SCORED | tc-temp-laxhigh-2026-08-31-gte78lt79f.POLYMARKET_US | 19.0 | 63 | 0 | 0.9900 | 0.5800 | 08-31 16:43 | 08-31 16:40 |
| LAX | 2026-09-01 | SCORED | tc-temp-laxhigh-2026-09-01-gte76lt77f.POLYMARKET_US | 299.9 | 1781 | 0 | 0.8300 | 77.0000 | - | - |
| MDW | 2026-08-31 | SCORED | tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US | 0.0 | 0 | 0 | - | - | - | - |
| MDW | 2026-09-01 | SCORED | tc-temp-mdwhigh-2026-09-01-gte93lt94f.POLYMARKET_US | 300.0 | 14293 | 9472 | 0.2100 | 25.0000 | 09-01 16:37 | 09-01 15:56 |
| MIA | 2026-08-30 | SCORED | tc-temp-miahigh-2026-08-30-gte91lt92f.POLYMARKET_US | 0.0 | 0 | 0 | - | - | - | - |
| MIA | 2026-08-31 | SCORED | tc-temp-miahigh-2026-08-31-gte91lt92f.POLYMARKET_US | 0.0 | 0 | 0 | - | - | - | - |
| MIA | 2026-09-01 | SCORED | tc-temp-miahigh-2026-09-01-gte89lt90f.POLYMARKET_US | 299.9 | 0 | 0 | - | - | - | - |
| SFO | 2026-08-31 | SCORED | tc-temp-sfohigh-2026-08-31-gte66lt67f.POLYMARKET_US | 19.0 | 59 | 0 | - | - | 08-31 16:40 | - |
| SFO | 2026-09-01 | SCORED | tc-temp-sfohigh-2026-09-01-gte70lt71f.POLYMARKET_US | 299.9 | 116 | 116 | 0.6500 | 18.0000 | - | - |

## K-A verdict

**UNDERPOWERED** -- n_afternoon=4 < 15; the sample cannot discriminate yet -- not a verdict in either direction

