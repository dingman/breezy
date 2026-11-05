# WP-7 -- REALISED post-fee PnL on the screen's own takes (2026-09-20)

Falsification of the `0b PASS` computed by `scripts/analysis/forecast_cheap_screen_wp7.py` (`4209fe3`). The registered §3 bar scores `p_fc - (price + fee)` -- MODEL-CLAIMED edge -- and settlement truth enters it only as a join filter, so the screen never asks whether the forecast was RIGHT. This artefact scores the SAME takes, made by the SAME take rule, against the NWS CLI settled daily high.

**In-sample by construction.** In-sample confirmation proves nothing; in-sample REFUTATION is decisive. A positive number below is reported as NOT REFUTED, never as a confirmation.

## What was reused verbatim

- take rule: `forecast_cheap_screen_wp7.screen_station_day`, all twelve registered variants, no filter added and no take dropped.
- fee: `forecast_tape_screen.venue_fee` -> `current_rung_hold.decision.fee_on_ask`, banker's-rounded to the cent, coefficient 0.0695.
- rung bounds: `h4_preliminary_economic_read.parse_rung` / `Rung.contains`, a CLOSED integer-°F interval. `gte86lt87f` settles YES on 86 AND on 87; the half-open reading leaves every odd degree in no rung at all.
- settlement truth: the NWS CLI finals the screen itself joins on.

- station-days scored (complete join): **73**
- peak RSS: **561 MB**

- frozen 0b error model on 5808 TRAIN station-days (not re-fitted)
- FORECAST ARCHIVE GAP for KLAX: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KMDW: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KMIA: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)
- FORECAST ARCHIVE GAP for KSFO: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21)

## Realised PnL per take, all twelve variants (§1(iv): every variant, not just the nine)

| variant | screen verdict | takes | win rate | mean realised | median realised | total realised |
|---|---|---|---|---|---|---|
| `A1-B1-C1` | CLEARS | 68 | 13.2% | -0.0081 | -0.0800 | -0.55 |
| `A1-B1-C2` | FAILS | 35 | 77.1% | +0.5489 | +0.6900 | +19.21 |
| `A1-B2-C1` | CLEARS | 69 | 52.2% | -0.0070 | +0.0100 | -0.48 |
| `A1-B2-C2` | CLEARS | 67 | 77.6% | +0.0879 | +0.1200 | +5.89 |
| `A2-B1-C1` | CLEARS | 70 | 18.6% | +0.0416 | -0.0500 | +2.91 |
| `A2-B1-C2` | FAILS | 35 | 68.6% | +0.5114 | +0.6900 | +17.90 |
| `A2-B2-C1` | CLEARS | 70 | 48.6% | +0.0969 | -0.0100 | +6.78 |
| `A2-B2-C2` | CLEARS | 65 | 81.5% | +0.2374 | +0.2400 | +15.43 |
| `A3-B1-C1` | CLEARS | 66 | 13.6% | -0.0077 | -0.0600 | -0.51 |
| `A3-B1-C2` | FAILS | 28 | 75.0% | +0.5096 | +0.6700 | +14.27 |
| `A3-B2-C1` | CLEARS | 66 | 45.5% | -0.0380 | -0.0250 | -2.51 |
| `A3-B2-C2` | CLEARS | 66 | 75.8% | +0.0879 | +0.1150 | +5.80 |

## Model-CLAIMED margin vs REALISED PnL -- the comparison that matters

| variant | median claimed | median realised | gap | mean claimed | mean realised | gap |
|---|---|---|---|---|---|---|
| `A1-B1-C1` | +0.0621 | -0.0800 | -0.1421 | +0.0775 | -0.0081 | -0.0856 |
| `A1-B1-C2` | +0.0317 | +0.6900 | +0.6583 | +0.0617 | +0.5489 | +0.4871 |
| `A1-B2-C1` | +0.0548 | +0.0100 | -0.0448 | +0.0731 | -0.0070 | -0.0801 |
| `A1-B2-C2` | +0.0470 | +0.1200 | +0.0730 | +0.0763 | +0.0879 | +0.0117 |
| `A2-B1-C1` | +0.0628 | -0.0500 | -0.1128 | +0.0892 | +0.0416 | -0.0476 |
| `A2-B1-C2` | +0.0395 | +0.6900 | +0.6505 | +0.0851 | +0.5114 | +0.4264 |
| `A2-B2-C1` | +0.0725 | -0.0100 | -0.0825 | +0.0937 | +0.0969 | +0.0032 |
| `A2-B2-C2` | +0.0395 | +0.2400 | +0.2005 | +0.1034 | +0.2374 | +0.1339 |
| `A3-B1-C1` | +0.0748 | -0.0600 | -0.1348 | +0.0885 | -0.0077 | -0.0962 |
| `A3-B1-C2` | +0.0357 | +0.6700 | +0.6343 | +0.0738 | +0.5096 | +0.4358 |
| `A3-B2-C1` | +0.0689 | -0.0250 | -0.0939 | +0.0965 | -0.0380 | -0.1345 |
| `A3-B2-C2` | +0.0567 | +0.1150 | +0.0583 | +0.1013 | +0.0879 | -0.0134 |

## 95% CI on MEAN realised PnL per take

Date is the single PRIMARY and DECISIONAL cluster (registration §2.2). The station-clustered interval is sensitivity only and is non-decisional -- with four stations it is a four-block resample and is reported for completeness.

| variant | CI (date, DECISIONAL) | CI (station, sensitivity only) |
|---|---|---|
| `A1-B1-C1` | [-0.0722, +0.0574] | [-0.0668, +0.0506] |
| `A1-B1-C2` | [+0.3470, +0.7515] | [+0.4564, +0.6131] |
| `A1-B2-C1` | [-0.0749, +0.0570] | [-0.0618, +0.0463] |
| `A1-B2-C2` | [+0.0086, +0.1631] | [+0.0712, +0.1052] |
| `A2-B1-C1` | [-0.0303, +0.1126] | [-0.0106, +0.0979] |
| `A2-B1-C2` | [+0.3614, +0.6612] | [+0.3523, +0.5962] |
| `A2-B2-C1` | [+0.0213, +0.1726] | [+0.0628, +0.1368] |
| `A2-B2-C2` | [+0.1590, +0.3048] | [+0.1765, +0.2875] |
| `A3-B1-C1` | [-0.0720, +0.0549] | [-0.0694, +0.0833] |
| `A3-B1-C2` | [+0.3386, +0.6995] | [+0.4342, +0.5663] |
| `A3-B2-C1` | [-0.1307, +0.0524] | [-0.0900, -0.0048] |
| `A3-B2-C2` | [-0.0036, +0.1774] | [+0.0119, +0.1436] |

## By side -- the B2 variants (B1 is YES-only by construction)

| variant | side | takes | win rate | mean realised | median claimed | total |
|---|---|---|---|---|---|---|
| `A1-B2-C1` | YES | 27 | 7.4% | -0.0519 | +0.0685 | -1.40 |
| `A1-B2-C1` | NO | 42 | 81.0% | +0.0219 | +0.0368 | +0.92 |
| `A1-B2-C2` | YES | 9 | 22.2% | +0.0244 | +0.0586 | +0.22 |
| `A1-B2-C2` | NO | 58 | 86.2% | +0.0978 | +0.0403 | +5.67 |
| `A2-B2-C1` | YES | 40 | 20.0% | +0.0645 | +0.0725 | +2.58 |
| `A2-B2-C1` | NO | 30 | 86.7% | +0.1400 | +0.0749 | +4.20 |
| `A2-B2-C2` | YES | 15 | 46.7% | +0.3527 | +0.0317 | +5.29 |
| `A2-B2-C2` | NO | 50 | 92.0% | +0.2028 | +0.0638 | +10.14 |
| `A3-B2-C1` | YES | 28 | 14.3% | -0.0093 | +0.0737 | -0.26 |
| `A3-B2-C1` | NO | 38 | 68.4% | -0.0592 | +0.0614 | -2.25 |
| `A3-B2-C2` | YES | 9 | 44.4% | +0.2422 | +0.1210 | +2.18 |
| `A3-B2-C2` | NO | 57 | 80.7% | +0.0635 | +0.0473 | +3.62 |

## The sub-0.02 ask subset -- where a model-error artefact would live

The screen flagged 1-cent asks that the model priced at 0.14-0.26. If that is a model error rather than an edge, this is the subset where it shows.

| variant | takes <= 0.02 | win rate | median claimed | mean realised | total |
|---|---|---|---|---|---|
| `A1-B1-C1` | 6 | 0.0% | +0.0557 | -0.0167 | -0.10 |
| `A1-B1-C2` | 2 | 0.0% | +0.0330 | -0.0150 | -0.03 |
| `A1-B2-C1` | 1 | 0.0% | +0.0631 | -0.0100 | -0.01 |
| `A1-B2-C2` | 1 | 0.0% | +0.0631 | -0.0100 | -0.01 |
| `A2-B1-C1` | 10 | 0.0% | +0.0640 | -0.0160 | -0.16 |
| `A2-B1-C2` | 7 | 14.3% | +0.1207 | +0.1271 | +0.89 |
| `A2-B2-C1` | 7 | 0.0% | +0.0818 | -0.0143 | -0.10 |
| `A2-B2-C2` | 5 | 0.0% | +0.1821 | -0.0120 | -0.06 |
| `A3-B1-C1` | 7 | 0.0% | +0.1210 | -0.0157 | -0.11 |
| `A3-B1-C2` | 3 | 0.0% | +0.1236 | -0.0167 | -0.05 |
| `A3-B2-C1` | 3 | 0.0% | +0.1210 | -0.0167 | -0.05 |
| `A3-B2-C2` | 3 | 0.0% | +0.1236 | -0.0133 | -0.04 |

Pooled across all twelve variants (takes are NOT independent across variants -- the same station-day recurs): n = 55, win rate 1.8%, median claimed +0.0818, mean realised +0.0031.

## Does the registered §3 statistic track money? No -- it tracks it BACKWARDS

Across the entire enumerated set (`K = 12`), rank-correlating each variant's
registered median CLAIMED margin against its MEAN REALISED PnL per take:

- Spearman **-0.755**, Pearson **-0.845**.

The three variants the screen FAILED (`A1-B1-C2`, `A2-B1-C2`, `A3-B1-C2` -- the
YES-only, pre-window-ask-screened cells, the ones carrying the LOWEST claimed
margins, one of them outright negative at -0.0048) are the three BEST realised
performers, averaging **+0.52 per take**. The nine that CLEARED average
**+0.054**, with four of the nine negative on the mean and five of the nine
negative on the MEDIAN realised PnL, and six of the nine carrying a
date-clustered 95% CI that straddles zero.

That is the falsification. §3's bar is not a weak estimator of edge; on this
corpus it is an ANTI-selector. Ranking variants by model-claimed margin
systematically prefers the cells that realise less money. A screen whose
ordering statistic is negatively rank-correlated with the realised outcome
cannot license a selection, and the Holm correction -- which corrects the
FAMILY-WISE error rate of a statistic, never the statistic's relevance --
does nothing about it.

## Verdict

**The `0b PASS` is REFUTED as edge evidence.**

Refuted, specifically, on all three of its load-bearing claims:

1. **The selection is anti-informative.** Spearman -0.755 between the ranking
   statistic and realised PnL. The screen's nine winners include its four
   worst-realising cells; its three rejects are its three best.
2. **The claimed edge does not survive contact with settlement.** Every
   CLEARING variant claimed a median margin of +0.047 .. +0.075. Five of the
   nine realised a NEGATIVE median. The median claimed-to-realised gap on the
   clearing cells runs from -0.14 to +0.20 -- an error far larger than the
   edge being claimed, which is the signature of a quantity that was never
   measured rather than one measured imprecisely.
3. **No clearing variant establishes a positive realised mean at the
   registration's own decisional cluster.** Six of the nine straddle zero on
   the date-clustered CI. The three that do not (`A1-B2-C2`, `A2-B2-C1`,
   `A2-B2-C2`) were selected out of twelve on a statistic now shown to be
   anti-correlated with the outcome, and carry no multiplicity correction on
   THIS statistic at all -- so they are not an edge claim, they are the
   max-over-twelve the registration was written to prevent.

**The sub-0.02 subset is the artefact, confirmed.** 55 pooled takes lifting an
ask at or below 0.02, on which the model claimed a median +0.082 edge, won
**1.8%** of the time (1 of 55) -- against a claimed win probability of roughly
0.10-0.28 implied by those margins at those prices. Eleven of the twelve
variants realise a NEGATIVE mean on this subset. The 1-cent ask is the market
correctly pricing a rung the model believes in; the model is wrong, and the
take rule's scan-every-rung-every-instant search finds precisely these
disagreements because they are the largest apparent margins on the tape. The
positive pooled mean (+0.0031) is one winning take at a 0.02 ask paying +0.98,
not a distribution with positive expectation.

**What is NOT claimed here.** The three high-realised C2 cells are not an edge
finding either. They are in-sample, they are the cells the registration
FAILED, their realised win rate comes with an n of 28-35, and reading them as
a strategy would be exactly the post-hoc selection this artefact refutes. They
are reported because §1(iv) requires every variant, and because their
existence is what makes the -0.755 correlation legible.

**Disposition.** No take rule, gate, threshold, filter or registered parameter
was changed to produce any number above. The forecast-conditioned rung model
does not have demonstrated tradeable edge on this corpus. A future economic
registration must score REALISED post-fee PnL, not `p_fc - (price + fee)`, and
must apply its multiplicity correction to that statistic.
