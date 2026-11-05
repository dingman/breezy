# WP-7b -- the MARKET scored as a competing forecaster (2026-09-20)

Governed by `docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md`, committed `3e67cbe` BEFORE this run. The three readings in its §3 were fixed in advance and the decision procedure below is applied mechanically.

## Corpus census (measured, before any statistic)

- station-days on the venue depth tape (4-station pool): **101**
- station-days with a COMPLETE join (truth + a cycle <= 09:00 LST): **93**
- station-days SCORED on the ask: **84**; on the mid: **24**
- rung-events emitted (every rung, no selection): **504**
- REFUSED -- ladder not a partition: 1; no liftable quote for some rung at the instant: 8; some rung unbid (mid undefined): 60
- REFUSED -- no forecast cycle at or before the instant: 0; no settlement truth: 8

- frozen 0b error model on 5808 TRAIN station-days (not re-fitted)

## (i) Paired Brier: forecast vs market, identical events

`Brier_fc - Brier_mkt` < 0 means the FORECAST is better. Every interval is a block bootstrap; the effective n is the CLUSTER count printed in the cell, never the row count (§6).

| market | rung-events | Brier_fc | Brier_mkt | difference | CI (station-day, PRIMARY) | CI (date) | CI (station) |
|---|---|---|---|---|---|---|---|
| `mid` | 144 | 0.13558 | 0.13299 | +0.00259 | [-0.01770, +0.02310] (clusters=24, max=6) | [-0.02031, +0.02092] (clusters=13, max=24) | [-0.01149, +0.01792] (clusters=4, max=60) |
| `ask` | 504 | 0.13149 | 0.13058 | +0.00090 | [-0.02147, +0.02079] (clusters=84, max=6) | [-0.02176, +0.02193] (clusters=21, max=24) | [-0.02358, +0.02496] (clusters=4, max=126) |

The reading below is taken on the MID, the first market forecast §2 names. It is INVARIANT to that choice here: both intervals straddle zero, so no choice of market moves the §3 branch.
The MID set is the smaller one BY REFUSAL, not by selection: a station-day whose ladder carries any unbid rung has no mid on the whole partition, and §2 refuses a partial ladder rather than imputing a bid. The ASK set is the full corpus and carries the same sign.

## (ii) Mean gap vs the monetisation hurdle

Hurdle = `venue_fee(ask) + half-spread`, the live rule's own fee, never a flat subtraction of theta. Take-eligible = both sides priced at L0, with NO edge filter (an edge filter is the selector §0 correction 4 names).

| take-eligible rung-events | mean \|p_fc - mid\| | mean hurdle | gap - hurdle |
|---|---|---|---|
| 144 | 0.12317 | 0.02063 | +0.10255 |

## (iii) Cross-rung consistency: sum(ask) over the complete partition (§4)

- instants measured: **84**

| statistic | min | p10 | p50 | p90 | max | mean |
|---|---|---|---|---|---|---|
| `sum(ask) - 1` | +0.0500 | +0.0700 | +0.1300 | +0.2200 | +2.9000 | +0.2532 |
| `sum(ask) + sum(fee) - 1` | +0.0500 | +0.1000 | +0.1800 | +0.2700 | +2.9100 | +0.2979 |
| thinnest L0 ask size on the ladder | 1.0 | 1.0 | 4.0 | 30.4 | 198.0 | 14.4 |

- instants with `sum(ask) <= 0.98` (a riskless long-only ladder buy WOULD be legal under `allow_short = False`): **0**, of which backed by an L0 depth of 1 contract somewhere on the ladder: **0**

## (iv) §5 free falsification -- the corrected WP-7 screen at the SINGLE instant

Pre-declared: realised PnL **UP** versus the instant-scan means the scan was harvesting noise and selection is confirmed; **unchanged** means the scan is not the driver. A1 (09-12 LST) is the only registered window that contains 09:00 LST; A2 (12-17) and A3 (10-11) cannot admit the pre-declared instant by construction and are NOT given an instant of their own.

| variant | takes (single instant) | win rate | mean realised | median realised | scan mean realised (`a0a9ea8`) | shift |
|---|---|---|---|---|---|---|
| `A1-B1-C1` | 82 | 12.2% | +0.0109 | -0.0500 | +0.0063 | +0.0046 |
| `A1-B1-C2` | 8 | 12.5% | +0.0700 | -0.0250 | +0.0093 | +0.0607 |

- `A1-B1-C1` 95% CI on mean realised (date-clustered, DECISIONAL): [-0.0534, +0.0827]
- `A1-B1-C2` 95% CI on mean realised (date-clustered, DECISIONAL): [-0.0800, +0.4500]

## The §3 reading the PRE-DECLARED decision procedure selects

**(b) SKILL IS IN THE PRICE -- L-7 confirmed on the traded unit. A SUCCESSFUL outcome: no decision rule can recover edge that is not there.**

Selected by: CI for Brier_fc - Brier_mkt = [-0.01770, +0.02310] over 24 clusters; upper bound >= 0, so the forecast is NOT significantly better than the price (it straddles zero or is worse).

A null here is a **NON-DETECTION AT SMALL MAGNITUDES**, never a proof of market efficiency (§6). The effective n is the cluster count above, not the rung-event count.

## Step-5 qualifying rate (AUD-02 completion plan §3)

`yes_ask >= 0.70` AND `sum(ask) <= 1.20` over the complete partition, at the 09:00 LST instant; YES side only (the NO leg is not captured).

Window (climate-day, inclusive both ends): since=2026-09-21 until=open. Station-days admitted in window (n): **12**.
- no FORECAST ARCHIVE GAP recorded for this corpus load
- qualifying events: 0; qualifying station-days: 0 of 12 (0.0000)
