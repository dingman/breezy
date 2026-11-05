# WP-7b -- the MARKET scored as a competing forecaster (2026-09-20)

Governed by `docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md`, committed `3e67cbe` BEFORE this run. The three readings in its §3 were fixed in advance and the decision procedure below is applied mechanically.

## Corpus census (measured, before any statistic)

- station-days on the venue depth tape (4-station pool): **81**
- station-days with a COMPLETE join (truth + a cycle <= 09:00 LST): **73**
- station-days SCORED on the ask: **64**; on the mid: **12**
- rung-events emitted (every rung, no selection): **384**
- REFUSED -- ladder not a partition: 1; no liftable quote for some rung at the instant: 8; some rung unbid (mid undefined): 52
- REFUSED -- no forecast cycle at or before the instant: 0; no settlement truth: 8

- frozen 0b error model on 5808 TRAIN station-days (not re-fitted)
- FORECAST ARCHIVE GAP for KLAX: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KMDW: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KMIA: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KSFO: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)

## (i) Paired Brier: forecast vs market, identical events

`Brier_fc - Brier_mkt` < 0 means the FORECAST is better. Every interval is a block bootstrap; the effective n is the CLUSTER count printed in the cell, never the row count (§6).

| market | rung-events | Brier_fc | Brier_mkt | difference | CI (station-day, PRIMARY) | CI (date) | CI (station) |
|---|---|---|---|---|---|---|---|
| `mid` | 72 | 0.12949 | 0.13735 | -0.00786 | [-0.03170, +0.01677] (clusters=12, max=6) | [-0.03198, +0.01284] (clusters=9, max=18) | [-0.01475, +0.01699] (clusters=3, max=42) |
| `ask` | 384 | 0.13090 | 0.13369 | -0.00278 | [-0.02950, +0.02240] (clusters=64, max=6) | [-0.03269, +0.02347] (clusters=16, max=24) | [-0.02939, +0.03067] (clusters=4, max=96) |

The reading below is taken on the MID, the first market forecast §2 names. It is INVARIANT to that choice here: both intervals straddle zero, so no choice of market moves the §3 branch.
The MID set is the smaller one BY REFUSAL, not by selection: a station-day whose ladder carries any unbid rung has no mid on the whole partition, and §2 refuses a partial ladder rather than imputing a bid. The ASK set is the full corpus and carries the same sign.

## (ii) Mean gap vs the monetisation hurdle

Hurdle = `venue_fee(ask) + half-spread`, the live rule's own fee, never a flat subtraction of theta. Take-eligible = both sides priced at L0, with NO edge filter (an edge filter is the selector §0 correction 4 names).

| take-eligible rung-events | mean \|p_fc - mid\| | mean hurdle | gap - hurdle |
|---|---|---|---|
| 72 | 0.10251 | 0.02083 | +0.08168 |

## (iii) Cross-rung consistency: sum(ask) over the complete partition (§4)

- instants measured: **64**

| statistic | min | p10 | p50 | p90 | max | mean |
|---|---|---|---|---|---|---|
| `sum(ask) - 1` | +0.0500 | +0.0700 | +0.1400 | +0.6200 | +2.9000 | +0.2913 |
| `sum(ask) + sum(fee) - 1` | +0.0500 | +0.1000 | +0.1800 | +0.6800 | +2.9100 | +0.3353 |
| thinnest L0 ask size on the ladder | 1.0 | 1.0 | 4.0 | 32.0 | 198.0 | 15.7 |

- instants with `sum(ask) <= 0.98` (a riskless long-only ladder buy WOULD be legal under `allow_short = False`): **0**, of which backed by an L0 depth of 1 contract somewhere on the ladder: **0**

## (iv) §5 free falsification -- the corrected WP-7 screen at the SINGLE instant

Pre-declared: realised PnL **UP** versus the instant-scan means the scan was harvesting noise and selection is confirmed; **unchanged** means the scan is not the driver. A1 (09-12 LST) is the only registered window that contains 09:00 LST; A2 (12-17) and A3 (10-11) cannot admit the pre-declared instant by construction and are NOT given an instant of their own.

| variant | takes (single instant) | win rate | mean realised | median realised | scan mean realised (`a0a9ea8`) | shift |
|---|---|---|---|---|---|---|
| `A1-B1-C1` | 62 | 11.3% | +0.0113 | -0.0500 | +0.0063 | +0.0050 |
| `A1-B1-C2` | 7 | 14.3% | +0.0829 | -0.0300 | +0.0093 | +0.0736 |

- `A1-B1-C1` 95% CI on mean realised (date-clustered, DECISIONAL): [-0.0557, +0.0867]
- `A1-B1-C2` 95% CI on mean realised (date-clustered, DECISIONAL): [-0.0856, +0.5440]

## The §3 reading the PRE-DECLARED decision procedure selects

**(b) SKILL IS IN THE PRICE -- L-7 confirmed on the traded unit. A SUCCESSFUL outcome: no decision rule can recover edge that is not there.**

Selected by: CI for Brier_fc - Brier_mkt = [-0.03170, +0.01677] over 12 clusters; upper bound >= 0, so the forecast is NOT significantly better than the price (it straddles zero or is worse).

A null here is a **NON-DETECTION AT SMALL MAGNITUDES**, never a proof of market efficiency (§6). The effective n is the cluster count above, not the rung-event count.

---

## Coordinator verification and two corrections (2026-09-20)

Verified independently before accepting this result.

**Partition check — SOUND.** The closed reading does partition the integers on a
real ladder: `lt86f / gte86lt87f / gte88lt89f / gte90lt91f / gte92lt93f /
gte94f` covers every integer with no gap and no overlap, and
`assert_complete_partition`'s abutment test (`following.lower_f ==
previous.upper_f + 1`) is the correct test for it.

**Σask overround — REAL, not a defect.** A mean `Σask − 1` of +0.29 (max +2.90)
looked implausible enough to check. It is genuine: with six rungs quoted wide
in an illiquid book, asks near 1.00 on the several rungs nobody wants sum well
above 1. A 29% mean overround is a statement about how wide this market is, and
it independently corroborates the (b) reading — you cross an enormous spread to
express any view here.

**CORRECTION 1 — "B2 unevaluable" is WRONG.** `PREREG_WP7b_..._2026-09-20.md`
§9 records "B2 (NO-side) is unevaluable — all 605 tape directories are YES-leg,
zero `^no`." Measured against the tape root WP-7 actually reads
(`~/.local/share/breezy/catalog/quote_tape/polymarket_us`, `:825`):

| | count |
|---|---|
| instrument dirs under that root | 12,123 |
| `^no` dirs under that root | **180** |
| `^no` dirs holding parquet data | **180** |
| distinct NO-leg station-days | **30** (2026-09-14 … 2026-09-19, 5 stations × 6 days) |

So NO-leg depth tape EXISTS. B2 is **underpowered (30 station-days), not
unevaluable**. The "605 / zero `^no`" figure described some narrower subset and
was propagated by me as a statement about the corpus. Corrected here; the §9
text stands as written with this correction attached.

This does not disturb the (b) reading: the NO leg prices the same rung event,
so adding it cannot convert a null paired-Brier comparison into a positive one.

**CORRECTION 2 — the decisive detail is the gap, not the Brier alone.** Mean
`|p_fc − mid|` is **0.1025** while the paired Brier difference is
**−0.0079 with a CI straddling zero**. The model therefore disagrees with the
market by ten probability points on average **and buys no accuracy for it.**
That is the signature of noise, not of suppressed information — and it is
consistent with the rung family's measured under-confidence (mean signed
deviation +0.0790, sigma too wide). A model whose disagreement with the price
is uncorrelated with being right has nothing to monetise, regardless of the
decision rule wrapped around it.

---

## RETRACTION of "CORRECTION 1" (2026-09-20, same day)

**"CORRECTION 1 — B2 unevaluable is WRONG" is itself WRONG and is retracted.**
The ORIGINAL claim — that B2 (NO-side) is unevaluable — was CORRECT.

I counted directories matching `*^no*` under the tape root, confirmed they held
parquet, and concluded NO-leg price tape existed. It does not. Those are
Nautilus **instrument-definition** rows (`outcome='No'`, 5 rows, schema
`raw_symbol/maker_fee/…`), not prices. Broken down by data type:

| data type | `^no` dirs | total dirs |
|---|---|---|
| `binary_option` (instrument definitions) | **210** | 781 |
| `order_book_depths` | **0** | 606 |
| `quote_tick` | **0** | 569 |
| `trade_tick` | **0** | 101 |
| `mark_price_update` | **0** | 551 |

**The NO leg has never been priced.** B2 is not "underpowered at 30
station-days" — it is UNOBSERVED. The error was counting a match without
checking what the matched thing IS; the parquet-present check gave false
confidence because instrument definitions are also parquet.

Consequence: any hypothesis whose only long-only expression is a NO-leg buy
(`allow_short = False`) **cannot be evaluated from the existing archive at
all**, no matter how the YES ask is re-analysed.

## Follow-on ruling: "fade the market's overconfidence" — UNDERPOWERED-UNDETERMINED

The reliability gap that motivated this hypothesis is arithmetically real and
sign-stable, but it does not mean what it appears to.

**Real as arithmetic.** Market reliability deviation on the ask is
distinguishable from zero at every threshold ≥ 0.50, with station-day-clustered
CIs — not merely in the thin tail bins:

| region | n | clusters | dev (obs − p̄) | CI95 |
|---|---|---|---|---|
| ask ≥ 0.50 | 63 | 53 | −0.2665 | [−0.4076, −0.1064] |
| ask ≥ 0.70 | 19 | 14 | **−0.6389** | [−0.8233, −0.3823] |
| bin [0.9,1.0) | 12 | 9 | −0.7175 | [−0.9686, −0.4560] |

Sign-stable: 4/4 stations negative at ask ≥ 0.70; 7 of 9 dates negative.

**But the dominant driver is overround mislabelled as belief.** The high-ask
events sit on broken ladders: mean `Σask` on ladders CARRYING a high ask is
**2.3516** against 1.2913 corpus-wide. Eleven of nineteen sit at Σask 2.12–3.90
(SFO 2026-09-01: **Σask = 3.90**, four rungs quoted 0.92–0.99 simultaneously).
Six mutually exclusive rungs cannot each be ~97% likely. On those books the ask
is **not a probability** — it is a near-cap quote against no seller (L0 ask
sizes of 1, 7, 10, 11 contracts; YES half-spread on the high-ask subset
averages **0.1307** vs 0.0235 corpus-wide). The market is not overconfident
there; we were reading an illiquid quote as a belief.

**And the NO leg is not the cheap side.** Synthetic NO (buying the other five
rungs) costs a median **1.130** and up to 2.980 — on the junk ladders the NO
claim costs ~3× its maximum payout. Only 8 of 19 cost < 1.00 pre-fee. Fees are
not the constraint (θ·p·(1−p) is ~1¢ at these prices); the constraints are a
13-point half-spread and an unpriced NO book.

**PnL under the generous CLOB-complement assumption (`NO_ask = 1 − yes_bid`,
itself unverifiable):**

| rule | n | clusters | mean/contract | CI95 |
|---|---|---|---|---|
| every event, any ask | 293 | 64 | **−0.0110** | **[−0.0188, −0.0021]** |
| ask ≥ 0.70, any ladder | 14 | 13 | +0.3250 | [+0.1118, +0.5456] |
| ask ≥ 0.70, **Σask ≤ 1.20** | 8 | 8 | +0.3037 | **[−0.2200, +0.8250]** |

Indiscriminate NO buying **loses with a CI excluding zero** — both legs are
expensive, exactly as 29% overround implies. The significant-looking ask ≥ 0.70
row is carried by junk-ladder events whose assumed NO price is meaningless.
Strip them and the tradeable residue is **8 events / 8 clusters, CI straddling
zero, +2.43 total driven by two trades**. The 2026-09-19 holdout contains
**zero** qualifying events.

**VERDICT: UNDERPOWERED-UNDETERMINED.** Not refuted, not supported. It cannot
be ruled on from the archive, because the price of the only instrument that
could express it has never been recorded.

**Frozen confirmatory region (registered now, before any NO data exists):**
`yes_ask ≥ 0.70` AND `Σask over the complete partition ≤ 1.20` AND both sides
priced at L0, at the existing 09:00 LST instant. Statistic: mean realised
NO-leg PnL per contract at the ACTUALLY QUOTED NO ask, fee θ·p·(1−p)
banker's-rounded. Bar: station-day-clustered 95% CI strictly > 0. Data:
post-freeze station-days only, from the first day NO-leg depth is captured.
Power: ~0.5 qualifying events/station-day ⇒ ~60 station-days for n ≈ 30. One
region, one statistic, no sweep.
