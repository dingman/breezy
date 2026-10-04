# Market calibration scan (M1)

**SCREENING ONLY. This data never doubles as nomination evidence (FQ-R14): a positive cell is a hypothesis for forward days after a freeze, never a trade rule and never a nomination.**

Status: **VALID**
- Join coverage (validity, horizon): 1.0000; raw over all tape station-days: 0.8023; truth last day 2026-09-28
- Observations: 3977; theta 0.0695
- Windows without a Depth10 row: 326
- Reads the converted data/ catalog only (L-20): unconverted live/ streams are not scanned. The ask is the best level at size >= 1 of the first Depth10 row in each window: no depth walk, no slippage, no fill probability, so a positive cell is an upper bound. Overlapping rungs of one station-day are dependent; the day-block bootstrap is the only clustering applied.

**SCREENING ONLY: no cell survives Bonferroni; the scan can detect only edges >= 19.8c (median per-cell MDE at 80% power, Bonferroni; pooled MDE 0.6c) - a null here is NOT evidence of no edge.**

| window | side | ask bin | n | days | mean excess | CI95 lo | CI95 hi | p (Bonf.) | MDE80 |
|---|---|---|---|---|---|---|---|---|---|
| D_17Z | YES | 0.3-0.4 | 49 | 22 | +0.1416 | +0.0100 | +0.2957 | 0.577 | 0.2935 |
| D_12Z | NO | 0.4-0.5 | 42 | 22 | +0.0717 | -0.0667 | +0.2005 | 1.000 | 0.2712 |
| D_12Z | NO | 0.5-0.6 | 47 | 21 | +0.0781 | -0.0700 | +0.2184 | 1.000 | 0.3002 |
| D_17Z | NO | 0.4-0.5 | 33 | 24 | +0.0821 | -0.1210 | +0.2688 | 1.000 | 0.4014 |
| D_12Z | YES | 0.3-0.4 | 64 | 23 | +0.0347 | -0.0540 | +0.1269 | 1.000 | 0.1868 |
| D-1_18Z | NO | 0.9-1.0 | 330 | 23 | +0.0041 | -0.0123 | +0.0191 | 1.000 | 0.0322 |
| D_17Z | YES | 0.1-0.2 | 72 | 24 | +0.0058 | -0.0624 | +0.0778 | 1.000 | 0.1454 |
| D_12Z | YES | 0.1-0.2 | 91 | 25 | +0.0033 | -0.0597 | +0.0746 | 1.000 | 0.1390 |
| D_12Z | NO | 0.6-0.7 | 53 | 24 | -0.0000 | -0.1390 | +0.1340 | 1.000 | 0.2807 |
| D-1_18Z | NO | 0.6-0.7 | 83 | 22 | -0.0001 | -0.1032 | +0.0989 | 1.000 | 0.2069 |
| D_17Z | NO | 0.5-0.6 | 39 | 19 | -0.0044 | -0.1433 | +0.1246 | 1.000 | 0.2771 |
| D_17Z | NO | 0.9-1.0 | 204 | 26 | -0.0011 | -0.0235 | +0.0193 | 1.000 | 0.0437 |
| D-1_18Z | YES | 0.4-0.5 | 73 | 23 | -0.0201 | -0.1529 | +0.1347 | 1.000 | 0.2959 |
| D_12Z | YES | 0.2-0.3 | 73 | 23 | -0.0082 | -0.0708 | +0.0460 | 1.000 | 0.1197 |
| D-1_18Z | YES | 0.2-0.3 | 89 | 23 | -0.0113 | -0.0856 | +0.0576 | 1.000 | 0.1473 |
| D_17Z | YES | 0.4-0.5 | 36 | 21 | -0.0250 | -0.1777 | +0.1232 | 1.000 | 0.3096 |
| D-1_18Z | NO | 0.5-0.6 | 48 | 20 | -0.0313 | -0.1887 | +0.1073 | 1.000 | 0.3048 |
| D-1_18Z | NO | 0.8-0.9 | 94 | 23 | -0.0171 | -0.1028 | +0.0578 | 1.000 | 0.1649 |
| D-1_18Z | YES | 0.1-0.2 | 109 | 23 | -0.0150 | -0.0762 | +0.0553 | 1.000 | 0.1352 |
| D_12Z | NO | 0.8-0.9 | 81 | 24 | -0.0331 | -0.1184 | +0.0407 | 1.000 | 0.1643 |
| D_17Z | YES | 0.2-0.3 | 70 | 25 | -0.0343 | -0.1106 | +0.0500 | 1.000 | 0.1644 |
| D_17Z | YES | 0.6-0.7 | 31 | 21 | -0.1068 | -0.3106 | +0.0867 | 1.000 | 0.4113 |
| D_12Z | YES | 0.5-0.6 | 55 | 23 | -0.0738 | -0.1983 | +0.0523 | 1.000 | 0.2563 |
| D_12Z | NO | 0.9-1.0 | 292 | 25 | -0.0136 | -0.0373 | +0.0079 | 1.000 | 0.0465 |
| D-1_18Z | YES | 0.3-0.4 | 82 | 23 | -0.0691 | -0.1692 | +0.0377 | 1.000 | 0.2138 |
| D-1_18Z | NO | 0.7-0.8 | 94 | 22 | -0.0632 | -0.1371 | +0.0182 | 1.000 | 0.1599 |
| D_17Z | NO | 0.8-0.9 | 68 | 26 | -0.0881 | -0.2009 | +0.0124 | 1.000 | 0.2198 |
| D_17Z | NO | 0.6-0.7 | 32 | 20 | -0.1309 | -0.2827 | +0.0179 | 1.000 | 0.3120 |
| D_17Z | NO | 0.7-0.8 | 64 | 23 | -0.1028 | -0.2135 | +0.0063 | 1.000 | 0.2277 |
| D_12Z | NO | 0.7-0.8 | 83 | 25 | -0.0790 | -0.1561 | -0.0050 | 1.000 | 0.1555 |
| D_12Z | YES | 0.0-0.1 | 347 | 25 | -0.0185 | -0.0343 | -0.0008 | 1.000 | 0.0343 |
| D_17Z | YES | 0.5-0.6 | 33 | 21 | -0.1942 | -0.3483 | -0.0430 | 1.000 | 0.3142 |
| D-1_18Z | YES | 0.0-0.1 | 305 | 23 | -0.0227 | -0.0367 | -0.0053 | 1.000 | 0.0327 |
| D_12Z | YES | 0.4-0.5 | 56 | 23 | -0.1957 | -0.2957 | -0.1019 | 1.000 | 0.1984 |
| D_17Z | YES | 0.0-0.1 | 435 | 26 | -0.0166 | -0.0237 | -0.0080 | 1.000 | 0.0165 |
- Zero-variance (untestable) cells: 0

```json
{
  "tested_cells": 35,
  "estimable_cells": 35,
  "bonferroni_alpha_per_cell": 0.0014285714285714286,
  "resamples": 10000,
  "seed": 20260904,
  "best_cell_by_t": {
    "window": "D_17Z",
    "side": "YES",
    "ask_bin": "0.3-0.4"
  },
  "best_cell_p_bonferroni": 0.5774422557744225,
  "reality_check_p": 0.34866513348665135,
  "spa_p": 0.41555844415558446,
  "any_cell_bonferroni_significant": false,
  "median_cell_mde_80": 0.19840169995121232,
  "pooled_mde_80": 0.006359049836532759
}
```
