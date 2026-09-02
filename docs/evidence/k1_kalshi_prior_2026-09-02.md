# K1 on KALSHI -- a large-sample PRIOR for the cheap-D-1 family

Generated 2026-09-02T20:05:26Z

**THIS IS A PRIOR FOR THE FAMILY, MEASURED ON KALSHI HISTORY. It cannot estimate Polymarket.us's own settle rate.** The settlement leg is identical -- the same five NWS CLI stations, the same product. The ASK leg is a different venue with different participants, liquidity and tick regime. This measurement can tell us early whether the cheap-D-1 family is dead everywhere; it cannot tell us what Polymarket.us pays, which K1 on our own tape still has to measure (L-13: a statistic is not comparable across regimes it was not sampled from).

Regenerate: `python scripts/analysis/k1_kalshi_prior.py` (offline, from cache) or `--crawl` (network). Companion measurement on our own tape: `scripts/analysis/k1_cheap_open_settlement.py`. Evidence: `docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md`.

Every statistic below is produced by K1's OWN function objects -- `summarize_stratum`, `wilson_interval`, `break_even_probability`, `resolution_floor`, `required_n_to_discriminate`, `min_n_to_refute` -- imported, not re-derived. Exactly ONE input differs: `theta = 0.07` (Kalshi taker) against 0.06 on Polymarket.us. This is a DESCRIPTIVE settlement-frequency measurement plus a closed-form break-even comparison. No order, fill, position or P&L is simulated: Nautilus Trader is the exclusive owner of backtesting.

## 1. Crawl preflight

| Quantity | Count |
|---|---:|
| Series crawled | 5 |
| Settled markets listed | 31233 |
| Candlestick responses in cache | 31221 |
| Candlestick responses fetched this run | 47 |
| Fetch failures | 0 |
| Crawl complete | YES |

Series: KXHIGHNY, KXHIGHMIA, KXHIGHCHI, KXHIGHLAX, KXHIGHTSFO.

## 2. Population as implemented

One member per settled market whose `open_time` fell STRICTLY before its climate day began in local STANDARD time -- K1's own `is_pre_climate_day`, against the registry's fixed `std_utc_offset_hours`, never DST-aware. Kalshi's modern markets open 14:00Z on D-1, which clears that boundary at all five stations; the rule is nevertheless APPLIED rather than assumed, because 2021 markets opened at assorted hours.

**Ask at open** is taken from the FIRST 60-minute candlestick starting at the market's own `open_time`: `yes_ask.open` when it is a genuine offer (`0 < p < 1`), else `yes_ask.close`. A market that opens with an empty book reports `yes_ask.open = 1.0000`, which is *nobody is offering*, not a 100c offer -- K1's `is_genuine_ask` rejects `p >= 1` for exactly that reason. The hour's `low`/`high` are never used: they are the best/worst price over the window, and K1 refuses to trade a price that was not on the screen at the moment it looked.

K1's D-1 rule binds on the instant the price was OBSERVED, not on the market's open: on the `close` branch that instant is the END of the first hour, so a market opening shortly before local-standard midnight is excluded even though its `open_time` cleared the boundary. An intraday quote is the population K1 exists to exclude.

**Two divergences from K1, stated rather than hidden.** (1) Kalshi candlesticks carry NO size, so K1's `size > 0` leg cannot be replicated: whether a cheap ask was fillable AT SIZE is UNVERIFIED here. (2) On the `close` branch the price is the state of the offer at the END of the first hour, up to 60 minutes after K1's instant. The branch split is reported below, and the `open`-only sensitivity is reported alongside every headline figure.

**Settlement truth is the venue's own `result` field** on the settled market -- never re-derived from a strike. The tail markets' semantics ("greater than 90" resolving on `floor_strike = 90`) are an off-by-one trap, and the venue's paid result is the ground truth K1 wants anyway. Kalshi's settlement source is the SAME NWS CLI product as Breezy's (`CLINYC`, `CLIMIA`, `CLIMDW`, `CLILAX`, `CLISFO`), read via The Weather Company -- one hop more than Breezy's direct NWS path, same underlying.

| Stage | Count |
|---|---:|
| Settled markets listed | 31233 |
| Dropped: ticker not a weather bucket | 0 |
| Dropped: re-listed duplicate of an existing bucket | 12 |
| Dropped: series not one of the five | 0 |
| Dropped: no usable `open_time` | 0 |
| Dropped: opened after the climate day began | 78 |
| Dropped: ask-at-open OBSERVED after the climate day began | 2 |
| Dropped: no settled `result` | 0 |
| Dropped: non-binary result (void) | 2 |
| Dropped: no candlestick in cache | 0 |
| Dropped: venue has no candlestick for this market (404 on both endpoints) | 0 |
| Dropped: no genuine ask in the first hour | 816 |
| **MEASURED POPULATION** | **30323** |

Ask-at-open branch split: `yes_ask.open` supplied 17318, `yes_ask.close` supplied 13005.

### Coverage by era and station

| Era | Station | n | First climate day | Last climate day |
|---|---|---:|---|---|
| 2021-22 SINGLE-THRESHOLD | LAX | 0 | n/a | n/a |
| 2021-22 SINGLE-THRESHOLD | MDW | 1203 | 2021-08-20 | 2022-12-31 |
| 2021-22 SINGLE-THRESHOLD | MIA | 0 | n/a | n/a |
| 2021-22 SINGLE-THRESHOLD | NYC | 1224 | 2021-08-06 | 2022-12-31 |
| 2021-22 SINGLE-THRESHOLD | SFO | 0 | n/a | n/a |
| 2023+ EXHAUSTIVE-BUCKETS | LAX | 3629 | 2025-01-05 | 2026-09-01 |
| 2023+ EXHAUSTIVE-BUCKETS | MDW | 7903 | 2023-01-01 | 2026-09-01 |
| 2023+ EXHAUSTIVE-BUCKETS | MIA | 7120 | 2023-05-12 | 2026-09-01 |
| 2023+ EXHAUSTIVE-BUCKETS | NYC | 7863 | 2023-01-01 | 2026-09-01 |
| 2023+ EXHAUSTIVE-BUCKETS | SFO | 1381 | 2026-01-14 | 2026-09-01 |

## 3. Ask-at-open distribution (all measured members, all outcomes)

### 2021-22 SINGLE-THRESHOLD

| Ask at open | Count |
|---:|---:|
| 0.0100 | 7 |
| 0.0200 | 19 |
| 0.0300 | 3 |
| 0.0400 | 3 |
| 0.0500 | 7 |
| 0.0600 | 7 |
| 0.0700 | 9 |
| 0.0800 | 15 |
| 0.0900 | 22 |
| 0.1000 | 18 |
| _> 0.10 (not shown individually)_ | 2317 |

Min 0.0100, median 0.4000, max 0.9900, n=2427.

### 2023+ EXHAUSTIVE-BUCKETS

| Ask at open | Count |
|---:|---:|
| 0.0100 | 133 |
| 0.0200 | 323 |
| 0.0300 | 546 |
| 0.0400 | 674 |
| 0.0500 | 641 |
| 0.0600 | 370 |
| 0.0700 | 311 |
| 0.0800 | 264 |
| 0.0900 | 356 |
| 0.1000 | 494 |
| _> 0.10 (not shown individually)_ | 23784 |

Min 0.0100, median 0.5400, max 0.9900, n=27896.

## 4. Settlement frequency by era, station and cheap-ask stratum

Break-even is `ask + theta * ask * (1 - ask)` evaluated at the stratum THRESHOLD (the most expensive ask admitted), with `theta = 0.07` -- Kalshi's TAKER coefficient. `clears?` asks whether the Wilson 95% UPPER bound exceeds break-even.

**Era x station is the PRIMARY table.** 2021-22 markets were single-threshold, 2023+ exhaustive buckets: the cheap-ask fraction of an exhaustive ladder is structurally larger than that of a lone threshold, so the two eras are different populations. G-01 separately established that WFOs are not exchangeable, so stations are not pooled either. Everything pooled below is INDICATIVE ONLY.

### Era x station (PRIMARY)

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| 2021-22 SINGLE-THRESHOLD / LAX | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010693 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / LAX | 0.02 | 0 | 0 | n/a | n/a | n/a | 0.021372 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / LAX | 0.03 | 0 | 0 | n/a | n/a | n/a | 0.032037 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / LAX | 0.05 | 0 | 0 | n/a | n/a | n/a | 0.053325 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MDW | 0.01 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 0.010693 | YES | 0.5615 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MDW | 0.02 | 15 | 2 | 0.1333 | 0.0374 | 0.3788 | 0.021372 | YES | 0.2039 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MDW | 0.03 | 16 | 3 | 0.1875 | 0.0659 | 0.4301 | 0.032037 | YES | 0.1936 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MDW | 0.05 | 20 | 3 | 0.1500 | 0.0524 | 0.3604 | 0.053325 | YES | 0.1611 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MIA | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010693 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MIA | 0.02 | 0 | 0 | n/a | n/a | n/a | 0.021372 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MIA | 0.03 | 0 | 0 | n/a | n/a | n/a | 0.032037 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / MIA | 0.05 | 0 | 0 | n/a | n/a | n/a | 0.053325 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / NYC | 0.01 | 4 | 0 | 0.0000 | 0.0000 | 0.4899 | 0.010693 | YES | 0.4899 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / NYC | 0.02 | 11 | 1 | 0.0909 | 0.0162 | 0.3774 | 0.021372 | YES | 0.2588 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / NYC | 0.03 | 13 | 1 | 0.0769 | 0.0137 | 0.3331 | 0.032037 | YES | 0.2281 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / NYC | 0.05 | 19 | 1 | 0.0526 | 0.0094 | 0.2464 | 0.053325 | YES | 0.1682 | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / SFO | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010693 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / SFO | 0.02 | 0 | 0 | n/a | n/a | n/a | 0.021372 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / SFO | 0.03 | 0 | 0 | n/a | n/a | n/a | 0.032037 | - | n/a | UNDERPOWERED |
| 2021-22 SINGLE-THRESHOLD / SFO | 0.05 | 0 | 0 | n/a | n/a | n/a | 0.053325 | - | n/a | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / LAX | 0.01 | 50 | 0 | 0.0000 | 0.0000 | 0.0713 | 0.010693 | YES | 0.0713 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / LAX | 0.02 | 108 | 0 | 0.0000 | 0.0000 | 0.0343 | 0.021372 | YES | 0.0343 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / LAX | 0.03 | 212 | 1 | 0.0047 | 0.0008 | 0.0262 | 0.032037 | no | 0.0178 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / LAX | 0.05 | 412 | 12 | 0.0291 | 0.0167 | 0.0502 | 0.053325 | no | 0.0092 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / MDW | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010693 | - | n/a | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / MDW | 0.02 | 42 | 1 | 0.0238 | 0.0042 | 0.1232 | 0.021372 | YES | 0.0838 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / MDW | 0.03 | 141 | 4 | 0.0284 | 0.0111 | 0.0707 | 0.032037 | YES | 0.0265 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / MDW | 0.05 | 396 | 8 | 0.0202 | 0.0103 | 0.0394 | 0.053325 | no | 0.0096 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / MIA | 0.01 | 64 | 0 | 0.0000 | 0.0000 | 0.0566 | 0.010693 | YES | 0.0566 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / MIA | 0.02 | 201 | 1 | 0.0050 | 0.0009 | 0.0276 | 0.021372 | YES | 0.0188 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / MIA | 0.03 | 401 | 3 | 0.0075 | 0.0025 | 0.0218 | 0.032037 | no | 0.0095 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / MIA | 0.05 | 888 | 7 | 0.0079 | 0.0038 | 0.0162 | 0.053325 | no | 0.0043 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / NYC | 0.01 | 19 | 0 | 0.0000 | 0.0000 | 0.1682 | 0.010693 | YES | 0.1682 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / NYC | 0.02 | 92 | 0 | 0.0000 | 0.0000 | 0.0401 | 0.021372 | YES | 0.0401 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / NYC | 0.03 | 196 | 3 | 0.0153 | 0.0052 | 0.0440 | 0.032037 | YES | 0.0192 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / NYC | 0.05 | 459 | 6 | 0.0131 | 0.0060 | 0.0282 | 0.053325 | no | 0.0083 | FAMILY_DEAD |
| 2023+ EXHAUSTIVE-BUCKETS / SFO | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010693 | - | n/a | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / SFO | 0.02 | 13 | 0 | 0.0000 | 0.0000 | 0.2281 | 0.021372 | YES | 0.2281 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / SFO | 0.03 | 52 | 1 | 0.0192 | 0.0034 | 0.1012 | 0.032037 | YES | 0.0688 | UNDERPOWERED |
| 2023+ EXHAUSTIVE-BUCKETS / SFO | 0.05 | 162 | 2 | 0.0123 | 0.0034 | 0.0439 | 0.053325 | no | 0.0232 | FAMILY_DEAD |

### Pooled across stations, WITHIN era (INDICATIVE ONLY)

Pools cities but never eras. Reported for scale; G-01 says it is not the finding.

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| POOLED / 2021-22 SINGLE-THRESHOLD | 0.01 | 7 | 0 | 0.0000 | 0.0000 | 0.3543 | 0.010693 | YES | 0.3543 | UNDERPOWERED |
| POOLED / 2021-22 SINGLE-THRESHOLD | 0.02 | 26 | 3 | 0.1154 | 0.0400 | 0.2898 | 0.021372 | YES | 0.1287 | UNDERPOWERED |
| POOLED / 2021-22 SINGLE-THRESHOLD | 0.03 | 29 | 4 | 0.1379 | 0.0550 | 0.3056 | 0.032037 | YES | 0.1170 | UNDERPOWERED |
| POOLED / 2021-22 SINGLE-THRESHOLD | 0.05 | 39 | 4 | 0.1026 | 0.0406 | 0.2358 | 0.053325 | YES | 0.0897 | UNDERPOWERED |
| POOLED / 2023+ EXHAUSTIVE-BUCKETS | 0.01 | 133 | 0 | 0.0000 | 0.0000 | 0.0281 | 0.010693 | YES | 0.0281 | UNDERPOWERED |
| POOLED / 2023+ EXHAUSTIVE-BUCKETS | 0.02 | 456 | 2 | 0.0044 | 0.0012 | 0.0158 | 0.021372 | no | 0.0084 | FAMILY_DEAD |
| POOLED / 2023+ EXHAUSTIVE-BUCKETS | 0.03 | 1002 | 12 | 0.0120 | 0.0069 | 0.0208 | 0.032037 | no | 0.0038 | FAMILY_DEAD |
| POOLED / 2023+ EXHAUSTIVE-BUCKETS | 0.05 | 2317 | 35 | 0.0151 | 0.0109 | 0.0209 | 0.053325 | no | 0.0017 | FAMILY_DEAD |

### Pooled across BOTH eras (INDICATIVE ONLY -- crosses the regime break)

A pooled rate across the regime break is the one result the evidence doc forbids as a finding. It appears here ONLY alongside the stratified tables above, for scale, and must never be quoted alone.

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| POOLED / ALL ERAS | 0.01 | 140 | 0 | 0.0000 | 0.0000 | 0.0267 | 0.010693 | YES | 0.0267 | UNDERPOWERED |
| POOLED / ALL ERAS | 0.02 | 482 | 5 | 0.0104 | 0.0044 | 0.0241 | 0.021372 | YES | 0.0079 | UNDERPOWERED |
| POOLED / ALL ERAS | 0.03 | 1031 | 16 | 0.0155 | 0.0096 | 0.0251 | 0.032037 | no | 0.0037 | FAMILY_DEAD |
| POOLED / ALL ERAS | 0.05 | 2356 | 39 | 0.0166 | 0.0121 | 0.0225 | 0.053325 | no | 0.0016 | FAMILY_DEAD |

### Sensitivity: `yes_ask.open` branch only (no close-of-hour fallback)

The subset whose ask-at-open came from the first candlestick's `open` -- i.e. an offer standing at the open INSTANT, with no up-to-60-minute latency. Smaller and therefore weaker, but free of divergence (2).

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| OPEN-ONLY / 2021-22 SINGLE-THRESHOLD | 0.01 | 6 | 0 | 0.0000 | 0.0000 | 0.3903 | 0.010693 | YES | 0.3903 | UNDERPOWERED |
| OPEN-ONLY / 2021-22 SINGLE-THRESHOLD | 0.02 | 24 | 2 | 0.0833 | 0.0232 | 0.2585 | 0.021372 | YES | 0.1380 | UNDERPOWERED |
| OPEN-ONLY / 2021-22 SINGLE-THRESHOLD | 0.03 | 26 | 3 | 0.1154 | 0.0400 | 0.2898 | 0.032037 | YES | 0.1287 | UNDERPOWERED |
| OPEN-ONLY / 2021-22 SINGLE-THRESHOLD | 0.05 | 29 | 3 | 0.1034 | 0.0358 | 0.2639 | 0.053325 | YES | 0.1170 | UNDERPOWERED |
| OPEN-ONLY / 2023+ EXHAUSTIVE-BUCKETS | 0.01 | 2 | 0 | 0.0000 | 0.0000 | 0.6576 | 0.010693 | YES | 0.6576 | UNDERPOWERED |
| OPEN-ONLY / 2023+ EXHAUSTIVE-BUCKETS | 0.02 | 13 | 0 | 0.0000 | 0.0000 | 0.2281 | 0.021372 | YES | 0.2281 | UNDERPOWERED |
| OPEN-ONLY / 2023+ EXHAUSTIVE-BUCKETS | 0.03 | 144 | 3 | 0.0208 | 0.0071 | 0.0595 | 0.032037 | YES | 0.0260 | UNDERPOWERED |
| OPEN-ONLY / 2023+ EXHAUSTIVE-BUCKETS | 0.05 | 426 | 3 | 0.0070 | 0.0024 | 0.0205 | 0.053325 | no | 0.0089 | FAMILY_DEAD |

## 5. Power

To distinguish a true settle rate of 3% (a real edge at a 1c ask) from 1% (no edge) at 95% confidence requires **n = 96** qualifying observations per cell -- K1's own `required_n_to_discriminate`, unchanged.

That is only the DISCRIMINATION sample. The binding constraint on a FAMILY DEAD verdict is stricter: the Wilson 95% UPPER bound must fall to break-even even when NOTHING settles YES, and at zero events that bound is `z^2 / (n + z^2)`.

| Stratum (ask <=) | Break-even (theta=0.07) | n to discriminate 3% from 1% | n to REFUTE at zero YES |
|---:|---:|---:|---:|
| 0.01 | 0.010693 | 96 | 356 |
| 0.02 | 0.021372 | 96 | 176 |
| 0.03 | 0.032037 | 96 | 117 |
| 0.05 | 0.053325 | 96 | 69 |

| Cell | Largest n reached |
|---|---:|
| POOLED / 2021-22 SINGLE-THRESHOLD | 39 |
| POOLED / 2023+ EXHAUSTIVE-BUCKETS | 2317 |
| POOLED / ALL ERAS | 2356 |

At n = 2356 the smallest Wilson 95% upper bound obtainable -- at ZERO observed YES settlements -- is 0.001628. Any break-even below that figure is UNREACHABLE with the corpus on hand.

### Effective sample: the markets are clustered, and NOT independent

| Era | Measured markets | Distinct station-days | Markets per station-day |
|---|---:|---:|---:|
| 2021-22 SINGLE-THRESHOLD | 2427 | 836 | 2.90 |
| 2023+ EXHAUSTIVE-BUCKETS | 27896 | 4696 | 5.94 |
| ALL | 30323 | 5532 | 5.48 |

**Buckets within one station-day are NOT independent.** In the exhaustive-bucket era the ~6 markets of a station-day PARTITION the same outcome: exactly one settles YES, so the rest are forced to NO. Observations inside a day are therefore negatively correlated, the Wilson intervals above are narrower than the true uncertainty, and the EFFECTIVE sample is closer to the station-day count than to n. K1 carries this caveat on its own tape; it binds at least as hard here, where the ladder is exhaustive. Treat every n above as an upper bound on information, not a count of independent trials.

## 6. VERDICT

**UNDERPOWERED -- INCONCLUSIVE**

Computed as a CONJUNCTION over eras -- each era's verdict from K1's own `_overall_verdict`, then combined -- never from the pooled-across-eras table, which the evidence doc forbids as a finding. Per era: 2021-22 SINGLE-THRESHOLD = UNDERPOWERED -- INCONCLUSIVE; 2023+ EXHAUSTIVE-BUCKETS = UNDERPOWERED -- INCONCLUSIVE.

Reason: **MIXED -- some cells have too few observations, others have adequate n with an interval that still straddles break-even**.

No era's strata jointly clear the 3%-versus-1% discrimination at 95% confidence. The discrimination sample is n = 96 per cell; the undecided cells and their reached n are:

| Era | Ask <= | n | Wilson 95% | Break-even |
|---|---:|---:|---|---:|
| 2021-22 SINGLE-THRESHOLD | 0.01 | 7 | [0.0000, 0.3543] | 0.010693 |
| 2021-22 SINGLE-THRESHOLD | 0.02 | 26 | [0.0400, 0.2898] | 0.021372 |
| 2021-22 SINGLE-THRESHOLD | 0.03 | 29 | [0.0550, 0.3056] | 0.032037 |
| 2021-22 SINGLE-THRESHOLD | 0.05 | 39 | [0.0406, 0.2358] | 0.053325 |
| 2023+ EXHAUSTIVE-BUCKETS | 0.01 | 133 | [0.0000, 0.0281] | 0.010693 |

### What this verdict does and does not license

**THIS IS A PRIOR FOR THE FAMILY, MEASURED ON KALSHI HISTORY. It cannot estimate Polymarket.us's own settle rate.** The settlement leg is identical -- the same five NWS CLI stations, the same product. The ASK leg is a different venue with different participants, liquidity and tick regime. This measurement can tell us early whether the cheap-D-1 family is dead everywhere; it cannot tell us what Polymarket.us pays, which K1 on our own tape still has to measure (L-13: a statistic is not comparable across regimes it was not sampled from).

A FAMILY DEAD reading here is strong evidence about the FAMILY, because the settlement leg is identical and the sample is three orders of magnitude larger than ours. A FAMILY SURVIVES reading here licenses nothing on Polymarket.us on its own: the edge would still have to exist in OUR book, at OUR asks, against OUR fee -- which only K1 on our own tape can measure. Neither reading moves the mechanical go-live date, which is gated on the execution spine, not on data.

