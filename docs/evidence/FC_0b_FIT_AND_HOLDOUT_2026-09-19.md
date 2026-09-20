# Stage 0b -- forecast skill vs a baseline ladder, 2025 holdout (WP-6)

Verdict: **SCORED**

## What this study claims -- and what it does not

THIS MEASURES FORECAST SKILL, NOT TRADEABLE EDGE. The corpus contains no venue price, no ask, no bid, no fee, no fill and no liftability -- so no number in this artefact is, or implies, an economic result. The venue prices the SAME public NBS guidance scored here, so beating climatology or persistence says nothing about beating the market: the market has the forecast too. The tradeable quantity is p_fc - (ask + theta) with theta = 0.0695, and a 6.95-point fee is large relative to any plausible residual mispricing of a public forecast. Establishing an economic claim requires joining the archived offer tape to these station-days and measuring p_fc against PRICE. That is WP-7. It is not done here and must not be inferred from here.

## Why persistence, not climatology, is the headline

The headline is forecast vs PERSISTENCE, not forecast vs climatology. The declared event is 'settled >= the TRAIN per-(station, month) median', which pins ANY climatology near the constant-predictor Brier of p*(1-p): measured, climatology beats a coin flip by ~1.5-1.8% pooled and LOSES to one at KSFO. A difference against a baseline that cannot move is near-tautological and carries no information about the forecast, so it has been withdrawn as the headline. Persistence -- yesterday's settled high, given the SAME train-fitted bias and sigma treatment the forecast gets -- knows the season, the station and the current regime, and is a real competitor. Brier Skill Scores against the constant base-rate reference are reported for every model so no conclusion rests on a chosen baseline at all.

Trial unit: one station-day. Train 2021-01-01 .. 2024-12-31 (n=5808); holdout 2025-01-01 .. 2025-12-31 (n=1441).

| station | holdout station-days |
|---|---|
| KLAX | 361 |
| KMDW | 364 |
| KMIA | 357 |
| KSFO | 359 |

Non-parametric cross-check: a train empirical-frequency climatology (+/-7-DOY window) scores Brier 0.252559 on the headline family, next to the Gaussian climatology's 0.246022. The two agree, which shows the near-coin-flip climatology score is a property of the EVENT, not of the Gaussian assumption.

## Family: median

n=1426 trials, base rate 0.5288.

| model | Brier | BSS vs constant base rate |
|---|---|---|
| `p_constant` | 0.249173 | +0.0000 |
| `p_clim` | 0.246022 | +0.0126 |
| `p_persistence` | 0.182074 | +0.2693 |
| `p_fc` | 0.101285 | +0.5935 |

| vs | cluster | clusters | max cluster | Brier_fc - Brier_ref | 95% CI |
|---|---|---|---|---|---|
| `p_persistence` | date | 363 | 4 | -0.080789 | [-0.095137, -0.067515] |
| `p_persistence` | station | 4 | 363 | -0.080789 | [-0.100756, -0.061391] |
| `p_clim` | date | 363 | 4 | -0.144737 | [-0.155685, -0.133576] |
| `p_clim` | station | 4 | 363 | -0.144737 | [-0.175209, -0.125296] |

REFUSED as degenerate: this family carries exactly one trial per station-day, so a station-day block bootstrap is an IID trial bootstrap. Intervals above are clustered by DATE (the shipped choice) and by STATION (only 4 clusters -- crude, but it is the interval that speaks to generalising to new stations).

Calibration leg (`|observed - predicted| <= 0.05`) for `p_fc`: **FAIL** (2 of 10 populated buckets fail; worst |dev| 0.1429).

| bucket | n | predicted | observed | \|dev\| | within eps |
|---|---|---|---|---|---|
| [0.0,0.1) | 298 | 0.022 | 0.020 | 0.0014 | yes |
| [0.1,0.2) | 122 | 0.147 | 0.115 | 0.0322 | yes |
| [0.2,0.3) | 64 | 0.252 | 0.109 | 0.1429 | **NO** |
| [0.3,0.4) | 101 | 0.349 | 0.347 | 0.0025 | yes |
| [0.4,0.5) | 79 | 0.447 | 0.418 | 0.0293 | yes |
| [0.5,0.6) | 51 | 0.559 | 0.529 | 0.0296 | yes |
| [0.6,0.7) | 108 | 0.652 | 0.694 | 0.0426 | yes |
| [0.7,0.8) | 90 | 0.747 | 0.800 | 0.0530 | **NO** |
| [0.8,0.9) | 127 | 0.859 | 0.882 | 0.0233 | yes |
| [0.9,1.0) | 386 | 0.978 | 0.966 | 0.0117 | yes |

Worst failing bucket: n=64, |dev|=0.1429, z=2.63. Buckets are evaluated independently at epsilon=0.05, so across ~10 populated buckets roughly half a miss is EXPECTED under a perfectly calibrated model. A small number of failures -- especially in a low-n bucket -- is reported, not acted on. Re-conditioning the model in response to one would be exactly the post-hoc move L-21 forbids.

| station | n | Brier_fc | Brier_persistence | fc - persistence |
|---|---|---|---|---|
| KLAX | 357 | 0.1152 | 0.1679 | -0.0527 |
| KMDW | 363 | 0.0523 | 0.1624 | -0.1101 |
| KMIA | 352 | 0.1135 | 0.2013 | -0.0879 |
| KSFO | 354 | 0.1253 | 0.1974 | -0.0721 |

## Family: rung

SECONDARY, AND ITS CLIMATOLOGY COMPARISON IS WITHDRAWN. Measured, the climatology baseline on the rung family scores WORSE than the constant base-rate reference; a baseline that loses to a constant is not a baseline, so the rung-vs-climatology difference is not reported. The rung's own forecast-side numbers ARE kept, because the 2F rung is the venue's actual trading unit. NOTE the correction to an earlier draft, which claimed this family OVERSTATES the forecast's advantage: that was backwards. The median family is the one sitting near its structural maximum; the rung gap is roughly HALF of it, on the unit that actually trades. The rung must be scored against PRICE in WP-7, never against climatology here.

n=1426 trials, base rate 0.4046.

| model | Brier | BSS vs constant base rate |
|---|---|---|
| `p_constant` | 0.240904 | -0.0000 |
| `p_clim` | 0.312285 | -0.2963 |
| `p_persistence` | 0.302861 | -0.2572 |
| `p_fc` | 0.234822 | +0.0252 |

| vs | cluster | clusters | max cluster | Brier_fc - Brier_ref | 95% CI |
|---|---|---|---|---|---|
| `p_persistence` | date | 363 | 4 | -0.068039 | [-0.078346, -0.057612] |
| `p_persistence` | station | 4 | 363 | -0.068039 | [-0.100729, -0.049770] |

Calibration leg (`|observed - predicted| <= 0.05`) for `p_fc`: **FAIL** (3 of 5 populated buckets fail; worst |dev| 0.1760).

| bucket | n | predicted | observed | \|dev\| | within eps |
|---|---|---|---|---|---|
| [0.1,0.2) | 14 | 0.181 | 0.357 | 0.1760 | **NO** |
| [0.2,0.3) | 596 | 0.257 | 0.305 | 0.0487 | yes |
| [0.3,0.4) | 462 | 0.356 | 0.431 | 0.0745 | **NO** |
| [0.4,0.5) | 200 | 0.460 | 0.525 | 0.0651 | **NO** |
| [0.5,0.6) | 154 | 0.528 | 0.558 | 0.0306 | yes |

Worst failing bucket: n=462, |dev|=0.0745, z=3.34. Buckets are evaluated independently at epsilon=0.05, so across ~10 populated buckets roughly half a miss is EXPECTED under a perfectly calibrated model. A small number of failures -- especially in a low-n bucket -- is reported, not acted on. Re-conditioning the model in response to one would be exactly the post-hoc move L-21 forbids.

**UNDER-CONFIDENCE, all 5 populated buckets.** Every bucket's observed frequency exceeds its predicted probability (mean signed deviation +0.0790), i.e. the fitted sigma is too WIDE. A uniformly under-confident model states probabilities lower than the frequencies it achieves, so a live 'take when p > ask + fee' rule fed by it UNDER-FIRES: it declines rungs whose realised hit rate would have cleared the threshold. Widening confidence is the safe direction for capital and the costly direction for opportunity; WP-7 must re-check sigma against PRICE before arming anything.

| station | n | Brier_fc | Brier_persistence | fc - persistence |
|---|---|---|---|---|
| KLAX | 357 | 0.2545 | 0.3099 | -0.0554 |
| KMDW | 363 | 0.2116 | 0.2639 | -0.0523 |
| KMIA | 352 | 0.2494 | 0.3668 | -0.1174 |
| KSFO | 354 | 0.2243 | 0.2722 | -0.0479 |

## Point error of the raw `txn` forecast by lead

| lead h | n | MAE F | RMSE F | mean signed error F |
|---|---|---|---|---|
| 17 | 1441 | 1.6738 | 2.3799 | +0.0597 |
| 23 | 1441 | 1.7078 | 2.4510 | +0.0673 |
| 29 | 1437 | 1.7627 | 2.5408 | +0.0731 |
| 35 | 1437 | 1.8789 | 2.6629 | +0.1016 |
| 41 | 1433 | 1.9491 | 2.7649 | +0.0775 |
| 47 | 1437 | 1.9555 | 2.7853 | +0.0974 |

## Next step

WP-7: join the archived offer tape to these station-days and measure `p_fc - (ask + 0.0695)`, under a variant set pre-declared with prediction-market sign-off BEFORE its first run. Until that exists there is no economic claim here, only a forecast-skill measurement.
