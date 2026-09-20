# Ruling: the forecast-edge hunt closes on Polymarket.us daily-high rungs

**Date:** 2026-09-20
**Status:** TERMINAL on this surface, by pre-registered procedure.
**Registration:** `docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md` (`3e67cbe`),
readings fixed in git BEFORE the first run.
**Evidence:** `docs/evidence/WP7b_MARKET_AS_FORECASTER_2026-09-20.md` (`b51fd8c`).

## 1. The finding

Scoring the venue price as a competing forecaster on identical rung-events —
one pre-declared 09:00 LST instant per station-day, every rung on the ladder,
no selection — selects pre-declared reading **(b): the skill is in the price.**

| market | events | Brier_fc | Brier_mkt | difference | CI (station-day) | clusters |
|---|---|---|---|---|---|---|
| mid | 72 | 0.12949 | 0.13735 | −0.00786 | [−0.03170, +0.01677] | 12 |
| ask | 384 | 0.13090 | 0.13369 | −0.00278 | [−0.02950, +0.02240] | 64 |

## 2. Why it is not merely a null — the mechanism

A near-parity Brier is ambiguous on its own: a model with good RESOLUTION but
poor RELIABILITY posts a weak Brier that recalibration repairs **without adding
information**. The scored model fails its own calibration gate (rung family:
3 of 5 buckets outside ε, under-confident in all five, mean signed deviation
+0.0790), so this had to be separated before closing. The Murphy decomposition
`Brier = reliability − resolution + uncertainty`:

| set | system | Brier | reliability | resolution | uncertainty |
|---|---|---|---|---|---|
| mid | forecast | 0.12949 | 0.00934 | 0.01580 | 0.13889 |
| mid | market | 0.13735 | 0.02015 | 0.02191 | 0.13889 |
| ask | forecast | 0.13090 | 0.00865 | **0.01554** | 0.13889 |
| ask | market | 0.13369 | 0.02668 | **0.03072** | 0.13889 |

`uncertainty = ō(1−ō) = (1/6)(5/6) = 5/36 = 0.138889`, exactly and identically
for both systems — exactly one rung of six settles YES. This is an exact
correctness check that the decomposition reconstructs both Briers.

**Decisive statistic `D = resolution_fc − resolution_mkt`:**

| set | D | CI95 (station-day clustered) | clusters |
|---|---|---|---|
| mid | −0.00611 | [−0.03922, +0.01744] | 12 |
| ask | **−0.01518** | **[−0.03229, −0.00373]** | 64 |

On the larger, stable set the sign is not merely null — it is **strictly
negative**. The market's resolution **exceeds** the forecast's by a factor of
**1.98×**. The price discriminates settled from unsettled rungs roughly twice
as well as the model does.

**The forecast is the BLAND forecaster.** Its competitive Brier is bought by low
reliability error (0.0087 against the market's 0.0267 — the market is 3.1×
worse calibrated), not by information. The market carries twice the resolution
and pays it back in miscalibration, quoting tail rungs near certainty that do
not settle (worst ask bins: p̄=0.967 → observed 0.250 at n=12; p̄=0.740 → 0.250
at n=4).

**So recalibration cannot rescue this.** There is no surplus resolution to
unlock, and low reliability error — the thing recalibration supplies — is
already the model's ONLY advantage. Confirmed directly by leave-one-station-
day-out Platt scaling (leakage-free: the held-out unit is the same cluster the
CI uses, so a station-day's ~6 correlated rungs are held out together):

| set | Brier_fc | Brier_fc recalibrated OOS | Brier_mkt | recal − mkt |
|---|---|---|---|---|
| mid | 0.12949 | 0.13397 (**worse**) | 0.13735 | −0.00338 |
| ask | 0.13090 | 0.13076 (+0.00014) | 0.13369 | −0.00293 |

Repairing reliability out-of-sample buys essentially nothing, and both remain
~0.003 from the market — an order of magnitude inside the ~0.02 hurdle.

**Binning sensitivity:** no binning (10-equal-width, 5-equal-width, 10-quantile)
yields a strictly positive CI on either set. The ask set is negative and stable
under all three.

## 3. Corroborating structure

Σask over 64 verified complete partitions is in **overround everywhere** —
mean +0.2913, min +0.0500, **zero** instants at or below 0.98. There is no
ladder arbitrage, and the spread you must cross to express any view is very
large. A 29% mean overround is an independent statement about why a small
informational edge could not be monetised here even if one existed.

## 4. Ruling

1. **Requirement 3 (measurable positive edge) is answered NEGATIVELY and
   terminally for this model on this surface.** The forecast carries no
   information beyond the price on Polymarket.us daily-high rungs; on the
   better-powered set it carries measurably LESS.
2. **This closes the forecast-edge hunt on this surface.** Per the
   pre-registration, (b) is a SUCCESSFUL outcome. No decision rule, threshold,
   sigma, or recalibration can recover edge that is not present.
3. **Do NOT proceed to WP-13 / WP-14 / WP-15 / WP-16 as planned.** Building a
   forecast-driven strategy whose forecast has lower resolution than the price
   would be building a machine to lose money. Registering a sequential test on
   it would spend α on a refuted hypothesis.
4. **`pm_us_crh_cont` is NOT displaced.** WP-19's displacement premise is void.

## 5. What the sample can and cannot support

This is a **non-detection at small magnitudes, never a proof of market
efficiency.** Effective n is 12 clusters (mid) and 64 (ask). The ask interval
excludes a forecast resolution advantage larger than ~0.004 but cannot exclude
one of 0.001–0.003. The mid set additionally fails a binning-stability check
and must not be read as a resolution result at all — the ask set, 64 clusters
and stable across three binnings, carries the conclusion.

The negative is about **this model, this venue, this contract (daily HIGH
temperature, 2 °F rungs, 5 cities)**. It is not a claim about weather
forecasting, other contracts, or other venues.

## 6. What survives, for the operator's decision

Not recommendations to act on — the surface choice is a product decision.

- **The market is very wide** (29% mean overround, zero sub-0.98 ladders).
  That is unfavourable to a taker and is the classic condition for a MAKER.
  `pm_us_crh_rest_v5` (resting bids) already exists in shadow and was never
  refuted by this work — it tests a different hypothesis (capture spread) than
  the one closed here (predict better than price).
- **Kalshi** is a different venue with 24 cities and a 5-minute cadence, and is
  parked on `wip/kalshi-s4-registry`. Nothing here transfers as a negative to
  it; it would need its own measurement.
- **The infrastructure built is sound and reusable**: point-in-time forecast
  ingest, the leakage-free scoring harness, the realized-fill learning loader,
  and a tally that now reconciles with its own residual ledger.

## 7. Discipline note

Three results were retracted on the way to this one, all of them mine: a
`+0.55`/take screen result that was look-ahead contamination; a "clean negative"
that was an underpowered non-detection; and a headline skill figure (BSS +0.594)
that belonged to a family the venue does not list and had already been withdrawn
in its own source document. Each was caught by pre-registration, adversarial
review, or an implausibility check — never by a green test suite.
