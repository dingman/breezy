# P(M > rung ceiling) climatology — the late-rise hazard, measured

Generated 2026-09-01T15:26:56+00:00 from `scripts/analysis/pmr_climatology_study.py`.
Archive cache: `/home/jon/.local/share/breezy/archive/settlement-alignment-cache` (zero network; cache misses are refused).
Corpus window: 2021-01-01 .. 2025-12-31.

## 0. What this document is

A physical/statistical measurement over historical NWS observations, in the
shape of `settlement_alignment_study.py` and the G-01 revision-rate study. It
is **not** a backtest, **not** a trading simulation and **not** a strategy
evaluation: no order, fill, position, fee or P&L appears anywhere in the
pipeline that produced it. NautilusTrader is the exclusive owner of
backtesting and execution; this is a parameter table it may later consume.

### Definitions

* `R(t)` — running maximum, in whole °F, as of the **end of local-standard
  hour `t`**. Built by one forward pass over instants sorted ascending, so no
  observation after `t` can influence it. Reset at local-standard midnight,
  the same boundary `breezy.ingest.records._climate_day_end_ns` defines.
* Rung — the venue's interior contracts are **closed** 2°F intervals
  `[A, A+1]` (`gte<A>lt<B>f` grammar). `upper_f = A + 1` is the last value
  that still settles YES.
* **`headroom = upper_f − R(t)` ∈ {0, 1}** — the primary conditioning
  variable, never pooled. A rule that fires on reaching a rung fires at
  `headroom = 0`.
* **Crossing** (PRIMARY) — `M > upper_f`. The loss event.
* Exceedance (SECONDARY) — `M > R(t)`. Reported for completeness; a 1°F rise
  inside the rung is harmless.
* `margin = R(t) − A = 1 − headroom`, carried because the surrounding studies
  speak in margins.
* Wilson 95% **UPPER** bounds throughout. The quantity is a failure
  probability, so the risk of being wrong is at the top of the interval. An
  empty cell reports `n/a`, never `0`.
* Completeness — a climate day is used only when **all 24** local-standard
  hours carry at least one observation.

### Two settlement bases

| basis | `M` | note |
|---|---|---|
| `cli` (PRIMARY) | NWS CLI final `tmax_f` (integer) | settlement truth; `M < R(t)` possible and counted as neg-basis, never as a crossing |
| `obs` (SECONDARY) | same day's ASOS maximum | self-consistent; `M >= R(t)` by construction |

`R(t)` exists only in ASOS units — the archive carries one CLI value per
climate day, so an hourly CLI-basis `R(t)` is not measurable. §2 reports the
METAR↔CLI basis instead.

## 0.1 Headline — computed, not asserted

Every line below is generated from the cells in §7. The reference level is
5% on the Wilson-95% **upper** bound of the crossing rate, held
for the rest of the climate day; seasons are pooled here for resolution
(§5.0), headroom never is. `REFUTED` means no such hour exists.

| station | basis | headroom | verdict | detail |
|---|---|---:|---|---|
| LAX | cli | 0 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| LAX | cli | 1 | **18h** | from 18h local standard the bound stays at or below 5.000% |
| LAX | obs | 0 | **14h** | from 14h local standard the bound stays at or below 5.000% |
| LAX | obs | 1 | **14h** | from 14h local standard the bound stays at or below 5.000% |
| MDW | cli | 0 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| MDW | cli | 1 | **16h** | from 16h local standard the bound stays at or below 5.000% |
| MDW | obs | 0 | **18h** | from 18h local standard the bound stays at or below 5.000% |
| MDW | obs | 1 | **16h** | from 16h local standard the bound stays at or below 5.000% |
| MIA | cli | 0 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| MIA | cli | 1 | **14h** | from 14h local standard the bound stays at or below 5.000% |
| MIA | obs | 0 | **15h** | from 15h local standard the bound stays at or below 5.000% |
| MIA | obs | 1 | **14h** | from 14h local standard the bound stays at or below 5.000% |
| NYC | cli | 0 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| NYC | cli | 1 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| NYC | obs | 0 | **19h** | from 19h local standard the bound stays at or below 5.000% |
| NYC | obs | 1 | **15h** | from 15h local standard the bound stays at or below 5.000% |
| SFO | cli | 0 | **REFUTED** | REFUTED: no hour exists after which the Wilson-95% upper bound stays at or below 5.000% for the rest of the climate day |
| SFO | cli | 1 | **15h** | from 15h local standard the bound stays at or below 5.000% |
| SFO | obs | 0 | **15h** | from 15h local standard the bound stays at or below 5.000% |
| SFO | obs | 1 | **15h** | from 15h local standard the bound stays at or below 5.000% |

And the reason the `cli` and `obs` columns differ — the residual risk once
the climate day is physically over (hour 23), where the `obs` basis has
**zero** crossings by construction:

| station | headroom | `cli` cross rate @23h | of which late-day physics | of which METAR↔CLI basis |
|---|---:|---:|---:|---:|
| LAX | 0 | 24.297% | 0.000% | 24.297% |
| LAX | 1 | 3.142% | 0.000% | 3.142% |
| MDW | 0 | 14.994% | 0.000% | 14.994% |
| MDW | 1 | 0.409% | 0.000% | 0.409% |
| MIA | 0 | 26.181% | 0.000% | 26.181% |
| MIA | 1 | 0.591% | 0.000% | 0.591% |
| NYC | 0 | 54.824% | 0.000% | 54.824% |
| NYC | 1 | 7.953% | 0.000% | 7.953% |
| SFO | 0 | 21.714% | 0.000% | 21.714% |
| SFO | 1 | 0.654% | 0.000% | 0.654% |

## 1. Corpus and denominators

| station | std offset | METAR obs | climate days | complete days | complete+CLI days | case rows (cli) | case rows (obs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| LAX | -8 | 558707 | 1826 | 1818 | 1812 | 43488 | 43632 |
| MDW | -6 | 553516 | 1826 | 1825 | 1825 | 43800 | 43800 |
| MIA | -5 | 561258 | 1826 | 1808 | 1798 | 43152 | 43392 |
| NYC | -5 | 53444 | 1818 | 1740 | 1736 | 41664 | 41760 |
| SFO | -8 | 560823 | 1826 | 1820 | 1793 | 43032 | 43680 |

Drop reasons (every row that did not reach a case):

| station | reason | count |
|---|---|---:|
| LAX | cli_final_without_max_time | 75 |
| LAX | cli_parse_error | 1 |
| LAX | incomplete_climate_day | 8 |
| LAX | missing_cli_final | 6 |
| LAX | missing_metar_t_group_row | 10053 |
| MDW | cli_final_without_max_time | 9 |
| MDW | cli_parse_error | 1 |
| MDW | incomplete_climate_day | 1 |
| MDW | missing_metar_t_group_row | 17008 |
| MIA | cli_final_without_max_time | 22 |
| MIA | cli_parse_error | 1 |
| MIA | incomplete_climate_day | 18 |
| MIA | missing_cli_final | 10 |
| MIA | missing_metar_t_group_row | 6410 |
| NYC | cli_final_without_max_time | 17 |
| NYC | cli_parse_error | 2 |
| NYC | incomplete_climate_day | 78 |
| NYC | missing_cli_final | 4 |
| NYC | missing_metar_t_group_row | 2307 |
| SFO | cli_final_without_max_time | 27 |
| SFO | cli_parse_error | 1 |
| SFO | incomplete_climate_day | 6 |
| SFO | missing_cli_final | 27 |
| SFO | missing_metar_t_group_row | 6134 |

## 2. METAR↔CLI basis — the unit mismatch, measured

`CLI tmax_f − ASOS daily max`, in whole °F, over complete days that also
carry a CLI final. A basis comparable to the 2°F rung width makes an
ASOS-driven `R(t)` unusable for an integer-settled ladder.

| station | n | mean | median | sd | P(=0) | P(|Δ|≥1) | P(|Δ|≥2) | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | 1812 | +0.103 | +0.0 | 0.758 | 56.126% | 43.874% | 2.704% | -1 | +7 |
| MDW | 1825 | -0.053 | +0.0 | 0.726 | 64.329% | 35.671% | 0.658% | -12 | +4 |
| MIA | 1798 | +0.118 | +0.0 | 0.662 | 59.511% | 40.489% | 1.168% | -1 | +5 |
| NYC | 1736 | +0.655 | +1.0 | 0.665 | 44.009% | 55.991% | 8.468% | -1 | +3 |
| SFO | 1793 | +0.050 | +0.0 | 0.747 | 58.840% | 41.160% | 1.339% | -8 | +7 |

Full basis histogram:

| station | Δ °F | n | share |
|---|---:|---:|---:|
| LAX | -1 | 338 | 18.653% |
| LAX | +0 | 1017 | 56.126% |
| LAX | +1 | 408 | 22.517% |
| LAX | +2 | 38 | 2.097% |
| LAX | +3 | 8 | 0.442% |
| LAX | +4 | 1 | 0.055% |
| LAX | +5 | 1 | 0.055% |
| LAX | +7 | 1 | 0.055% |
| MDW | -12 | 1 | 0.055% |
| MDW | -9 | 1 | 0.055% |
| MDW | -7 | 1 | 0.055% |
| MDW | -1 | 364 | 19.945% |
| MDW | +0 | 1174 | 64.329% |
| MDW | +1 | 275 | 15.068% |
| MDW | +2 | 7 | 0.384% |
| MDW | +3 | 1 | 0.055% |
| MDW | +4 | 1 | 0.055% |
| MIA | -1 | 270 | 15.017% |
| MIA | +0 | 1070 | 59.511% |
| MIA | +1 | 437 | 24.305% |
| MIA | +2 | 20 | 1.112% |
| MIA | +5 | 1 | 0.056% |
| NYC | -1 | 1 | 0.058% |
| NYC | +0 | 764 | 44.009% |
| NYC | +1 | 824 | 47.465% |
| NYC | +2 | 127 | 7.316% |
| NYC | +3 | 20 | 1.152% |
| SFO | -8 | 1 | 0.056% |
| SFO | -3 | 1 | 0.056% |
| SFO | -1 | 338 | 18.851% |
| SFO | +0 | 1055 | 58.840% |
| SFO | +1 | 376 | 20.970% |
| SFO | +2 | 15 | 0.837% |
| SFO | +3 | 2 | 0.112% |
| SFO | +4 | 1 | 0.056% |
| SFO | +5 | 3 | 0.167% |
| SFO | +7 | 1 | 0.056% |

## 3. Time of the daily maximum, `T*` — two independent estimates

Hours are local STANDARD time. The ASOS estimate is the first observation
attaining the day's maximum UNROUNDED reading — not the rounded series,
whose ties would break toward the morning and bias `T*` hours early. The
CLI estimate is the archived product's own
`MAXIMUM <v> <h:mm> <AM|PM>` field, whose column header declares `TIME (LST)`
— a claim this study measures rather than trusts (see §3.3). Breezy's
production parser discards that field; it is parsed here from raw text.

### 3.1 Distribution by station and season

| series | n | T* p05 / p25 / p50 / p75 / p95 (LST hour) | P(T* > 17:00) |
|---|---:|---|---:|
| LAX DJF ASOS | 448 | 10 / 11 / 12 / 13 / 14 | 1.786% |
| LAX DJF CLI | 447 | 11 / 12 / 13 / 14 / 16 | 2.908% |
| LAX MAM ASOS | 460 | 09 / 10 / 11 / 12 / 14 | 0.870% |
| LAX MAM CLI | 408 | 09 / 11 / 13 / 14 / 16 | 1.961% |
| LAX JJA ASOS | 458 | 08 / 10 / 11 / 12 / 14 | 0.000% |
| LAX JJA CLI | 434 | 09 / 12 / 13 / 14 / 15 | 0.000% |
| LAX SON ASOS | 452 | 09 / 10 / 11 / 12 / 13 | 0.000% |
| LAX SON CLI | 450 | 10 / 11 / 12 / 13 / 15 | 0.000% |
| MDW DJF ASOS | 451 | 00 / 10 / 13 / 14 / 22 | 11.752% |
| MDW DJF CLI | 448 | 00 / 13 / 15 / 17 / 23 | 22.768% |
| MDW MAM ASOS | 460 | 00 / 11 / 13 / 14 / 16 | 3.261% |
| MDW MAM CLI | 457 | 00 / 13 / 14 / 16 / 18 | 5.689% |
| MDW JJA ASOS | 459 | 08 / 11 / 13 / 14 / 15 | 0.000% |
| MDW JJA CLI | 458 | 10 / 13 / 14 / 15 / 17 | 0.873% |
| MDW SON ASOS | 455 | 00 / 11 / 13 / 14 / 15 | 1.758% |
| MDW SON CLI | 453 | 01 / 13 / 14 / 15 / 17 | 4.857% |
| MIA DJF ASOS | 450 | 09 / 11 / 12 / 13 / 15 | 0.444% |
| MIA DJF CLI | 447 | 11 / 13 / 14 / 15 / 16 | 1.566% |
| MIA MAM ASOS | 456 | 10 / 11 / 12 / 13 / 15 | 0.000% |
| MIA MAM CLI | 446 | 11 / 13 / 13 / 14 / 16 | 0.000% |
| MIA JJA ASOS | 450 | 09 / 10 / 11 / 13 / 14 | 0.000% |
| MIA JJA CLI | 448 | 10 / 12 / 13 / 14 / 16 | 0.223% |
| MIA SON ASOS | 452 | 09 / 11 / 12 / 13 / 14 | 0.221% |
| MIA SON CLI | 446 | 10 / 12 / 13 / 14 / 15 | 0.448% |
| NYC DJF ASOS | 421 | 00 / 11 / 13 / 14 / 22 | 12.114% |
| NYC DJF CLI | 419 | 00 / 13 / 15 / 16 / 23 | 20.048% |
| NYC MAM ASOS | 431 | 00 / 11 / 13 / 14 / 16 | 2.552% |
| NYC MAM CLI | 429 | 00 / 13 / 14 / 15 / 19 | 6.993% |
| NYC JJA ASOS | 449 | 10 / 11 / 12 / 14 / 16 | 0.223% |
| NYC JJA CLI | 442 | 11 / 12 / 13 / 15 / 17 | 2.489% |
| NYC SON ASOS | 439 | 00 / 11 / 13 / 13 / 16 | 3.645% |
| NYC SON CLI | 435 | 04 / 13 / 14 / 15 / 21 | 8.506% |
| SFO DJF ASOS | 450 | 04 / 12 / 14 / 15 / 17 | 3.111% |
| SFO DJF CLI | 442 | 12 / 14 / 15 / 16 / 21 | 9.050% |
| SFO MAM ASOS | 458 | 10 / 11 / 12 / 13 / 15 | 0.218% |
| SFO MAM CLI | 448 | 11 / 12 / 14 / 14 / 16 | 0.223% |
| SFO JJA ASOS | 458 | 10 / 11 / 12 / 13 / 14 | 0.000% |
| SFO JJA CLI | 441 | 11 / 13 / 13 / 14 / 15 | 0.454% |
| SFO SON ASOS | 454 | 10 / 12 / 13 / 14 / 15 | 0.000% |
| SFO SON CLI | 447 | 11 / 13 / 14 / 15 / 16 | 1.119% |

### 3.2 Full T* hour histogram (ASOS, share of season-days)

| station | season | n | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | DJF | 448 | 2.2 | 0.0 | 0.0 | 0.2 | 0.0 | 0.0 | 0.0 | 0.4 | 0.4 | 1.3 | 12.5 | 31.2 | 24.1 | 14.5 | 8.5 | 1.8 | 0.7 | 0.2 | 0.0 | 0.7 | 0.4 | 0.2 | 0.2 | 0.2 |
| LAX | MAM | 460 | 0.2 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 | 0.0 | 0.0 | 2.8 | 12.4 | 21.7 | 26.1 | 19.6 | 11.5 | 3.0 | 0.9 | 0.0 | 0.4 | 0.4 | 0.0 | 0.0 | 0.4 | 0.0 | 0.0 |
| LAX | JJA | 458 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 | 0.2 | 6.8 | 16.6 | 19.0 | 19.7 | 20.5 | 10.5 | 5.2 | 0.9 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| LAX | SON | 452 | 0.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 | 0.2 | 11.9 | 28.5 | 26.1 | 20.8 | 8.0 | 2.7 | 0.2 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| MDW | DJF | 451 | 16.0 | 0.9 | 1.1 | 0.2 | 0.4 | 1.3 | 0.0 | 0.2 | 1.1 | 1.1 | 2.9 | 6.4 | 11.8 | 19.5 | 14.4 | 6.4 | 2.7 | 1.8 | 1.1 | 1.6 | 1.3 | 1.1 | 2.7 | 4.0 |
| MDW | MAM | 460 | 10.0 | 0.7 | 0.2 | 0.0 | 0.0 | 0.0 | 0.7 | 0.9 | 0.9 | 3.7 | 4.3 | 7.8 | 13.7 | 18.0 | 17.8 | 13.3 | 4.1 | 0.7 | 1.1 | 0.0 | 0.2 | 0.7 | 0.9 | 0.4 |
| MDW | JJA | 459 | 2.6 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.4 | 0.4 | 1.3 | 2.6 | 5.7 | 12.2 | 19.4 | 24.2 | 20.0 | 7.6 | 2.4 | 0.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| MDW | SON | 455 | 8.1 | 0.4 | 0.2 | 0.2 | 0.0 | 0.2 | 0.4 | 0.4 | 0.4 | 1.8 | 5.7 | 12.3 | 16.9 | 26.6 | 17.1 | 5.3 | 0.7 | 1.3 | 0.0 | 0.0 | 0.4 | 0.0 | 0.7 | 0.7 |
| MIA | DJF | 450 | 3.1 | 0.0 | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 1.8 | 7.8 | 21.6 | 24.2 | 22.4 | 12.4 | 5.3 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 |
| MIA | MAM | 456 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.9 | 2.0 | 10.1 | 26.1 | 26.5 | 20.2 | 8.3 | 3.9 | 1.1 | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| MIA | JJA | 450 | 0.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 4.0 | 20.7 | 25.3 | 20.4 | 16.4 | 7.6 | 3.1 | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| MIA | SON | 452 | 1.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 | 0.2 | 0.7 | 5.1 | 16.2 | 25.0 | 25.9 | 14.8 | 8.2 | 1.8 | 0.2 | 0.2 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 | 0.0 |
| NYC | DJF | 421 | 12.1 | 0.7 | 1.0 | 0.7 | 0.7 | 1.0 | 1.0 | 0.2 | 1.0 | 0.5 | 2.6 | 6.4 | 15.9 | 17.6 | 16.9 | 7.4 | 1.0 | 1.4 | 1.4 | 1.7 | 2.1 | 0.7 | 1.2 | 5.0 |
| NYC | MAM | 431 | 8.6 | 0.2 | 0.2 | 0.2 | 0.0 | 0.2 | 0.2 | 0.5 | 0.9 | 1.4 | 4.2 | 9.0 | 20.6 | 19.3 | 19.3 | 9.5 | 2.1 | 0.9 | 0.2 | 0.7 | 0.2 | 0.5 | 0.2 | 0.7 |
| NYC | JJA | 449 | 2.2 | 0.2 | 0.0 | 0.0 | 0.2 | 0.0 | 0.0 | 0.4 | 0.0 | 1.6 | 5.8 | 17.8 | 29.6 | 16.5 | 12.2 | 7.8 | 4.2 | 1.1 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 |
| NYC | SON | 439 | 7.5 | 1.1 | 0.0 | 0.2 | 0.0 | 0.0 | 0.5 | 0.0 | 0.7 | 1.6 | 2.3 | 12.3 | 22.6 | 26.9 | 15.9 | 3.0 | 0.7 | 1.1 | 0.7 | 0.5 | 0.2 | 0.9 | 0.9 | 0.5 |
| SFO | DJF | 450 | 3.8 | 0.7 | 0.2 | 0.2 | 0.4 | 0.0 | 0.0 | 0.2 | 0.4 | 1.6 | 2.4 | 5.1 | 12.0 | 21.8 | 21.8 | 19.6 | 4.7 | 2.0 | 0.7 | 0.4 | 0.4 | 0.2 | 0.4 | 0.9 |
| SFO | MAM | 458 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 | 0.0 | 2.4 | 7.9 | 18.8 | 31.4 | 20.7 | 12.9 | 3.5 | 1.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 |
| SFO | JJA | 458 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 | 2.0 | 6.8 | 21.8 | 30.1 | 25.5 | 9.8 | 3.5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| SFO | SON | 454 | 0.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 | 0.2 | 1.3 | 3.3 | 13.2 | 22.9 | 26.2 | 20.9 | 8.6 | 2.0 | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### 3.3 CLI-stated hour minus ASOS hour — is the `(LST)` label true?

A systematic `+1` **confined to the DST months** (Apr–Oct) would show the
CLI time to be local DAYLIGHT time despite the `(LST)` column header. An
offset present in BOTH month groups is not DST aliasing — it is an
instrument/sampling difference (the CLI max comes from 1-minute ASOS data
and, per §2, usually reads 0–1°F above the 5-minute METAR series, so it
points at a peak minute the METAR series never sampled).

| station | n | mean Δ | mode Δ | P(Δ<0) | P(Δ=0) | P(Δ=+1) | DST-months mean Δ | DST-months mode Δ | DST P(Δ=+1) | STD-months mean Δ | STD-months mode Δ | STD P(Δ=+1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | 1739 | +1.470 | +0 | 0.805% | 32.030% | 30.995% | +1.526 | +0 | 27.463% | +1.394 | +1 | 35.831% |
| MDW | 1816 | +1.831 | +1 | 0.330% | 27.808% | 29.570% | +1.606 | +1 | 29.737% | +2.151 | +1 | 29.333% |
| MIA | 1787 | +1.564 | +1 | 0.504% | 26.973% | 29.491% | +1.499 | +1 | 30.755% | +1.657 | +1 | 27.703% |
| NYC | 1725 | +1.773 | +1 | 2.029% | 22.899% | 34.377% | +1.558 | +1 | 35.029% | +2.087 | +1 | 33.428% |
| SFO | 1778 | +1.340 | +0 | 0.506% | 34.646% | 34.477% | +1.196 | +0 | 32.883% | +1.541 | +1 | 36.707% |

## 4. Pre-registered decision rules — verdicts, reported verbatim

**PR-1.** *If `P(T* > 17:00 LST) > 0.05` at MDW, MIA or NYC, then a clock-based "after the peak" rule is PHYSICALLY FALSE at that station.*

| station | series | season | n | P(T* > 17:00) | verdict |
|---|---|---|---:|---:|---|
| MDW | ASOS | ALL | 1825 | 4.164% | not falsified |
| MDW | ASOS | DJF | 451 | 11.752% | **RULE FALSE at this station** |
| MDW | ASOS | MAM | 460 | 3.261% | not falsified |
| MDW | ASOS | JJA | 459 | 0.000% | not falsified |
| MDW | ASOS | SON | 455 | 1.758% | not falsified |
| MDW | CLI | ALL | 1816 | 8.480% | **RULE FALSE at this station** |
| MDW | CLI | DJF | 448 | 22.768% | **RULE FALSE at this station** |
| MDW | CLI | MAM | 457 | 5.689% | **RULE FALSE at this station** |
| MDW | CLI | JJA | 458 | 0.873% | not falsified |
| MDW | CLI | SON | 453 | 4.857% | not falsified |
| MIA | ASOS | ALL | 1808 | 0.166% | not falsified |
| MIA | ASOS | DJF | 450 | 0.444% | not falsified |
| MIA | ASOS | MAM | 456 | 0.000% | not falsified |
| MIA | ASOS | JJA | 450 | 0.000% | not falsified |
| MIA | ASOS | SON | 452 | 0.221% | not falsified |
| MIA | CLI | ALL | 1787 | 0.560% | not falsified |
| MIA | CLI | DJF | 447 | 1.566% | not falsified |
| MIA | CLI | MAM | 446 | 0.000% | not falsified |
| MIA | CLI | JJA | 448 | 0.223% | not falsified |
| MIA | CLI | SON | 446 | 0.448% | not falsified |
| NYC | ASOS | ALL | 1740 | 4.540% | not falsified |
| NYC | ASOS | DJF | 421 | 12.114% | **RULE FALSE at this station** |
| NYC | ASOS | MAM | 431 | 2.552% | not falsified |
| NYC | ASOS | JJA | 449 | 0.223% | not falsified |
| NYC | ASOS | SON | 439 | 3.645% | not falsified |
| NYC | CLI | ALL | 1725 | 9.391% | **RULE FALSE at this station** |
| NYC | CLI | DJF | 419 | 20.048% | **RULE FALSE at this station** |
| NYC | CLI | MAM | 429 | 6.993% | **RULE FALSE at this station** |
| NYC | CLI | JJA | 442 | 2.489% | not falsified |
| NYC | CLI | SON | 435 | 8.506% | **RULE FALSE at this station** |

**PR-2.** *If `T*` is BIMODAL at LAX or SFO, a single-hour threshold is false
there regardless of its value.* Criterion, fixed in advance: ≥2 local maxima
≥3h apart, each ≥10% of the season's days, with the trough
between them ≤60% of the smaller peak.

| station | season | n | verdict | detail |
|---|---|---:|---|---|
| LAX | DJF | 448 | unimodal | qualifying peaks: 11h 31.2% |
| LAX | MAM | 460 | unimodal | qualifying peaks: 11h 26.1% |
| LAX | JJA | 458 | unimodal | qualifying peaks: 12h 20.5% |
| LAX | SON | 452 | unimodal | qualifying peaks: 10h 28.5% |
| SFO | DJF | 450 | unimodal | qualifying peaks: 13h 21.8%, 14h 21.8% |
| SFO | MAM | 458 | unimodal | qualifying peaks: 12h 31.4% |
| SFO | JJA | 458 | unimodal | qualifying peaks: 12h 30.1% |
| SFO | SON | 454 | unimodal | qualifying peaks: 13h 26.2% |

**PR-3.** *A CLI final is implausible against its own ASOS series when its
`tmax_f` exceeds the day's ASOS maximum by >5°F,
or exceeds every ASOS reading within ±30 min
of its own stated time by the same margin. Implausible records are REPORTED
AND KEPT — they are the hazard, not outliers.*

Scanned over ALL parseable CLI products, PRELIMINARIES INCLUDED — the
archetype is a preliminary, and any rule reading a running max reads
preliminaries. A stated time with no ASOS observation inside the window is
counted separately as *uncorroborated*: that is a cadence artifact of an
hourly station, not a contradiction, and folding it in would put a bogus
bad-print rate on NYC alone.

| station | complete+CLI days | implausible products | of which PRELIMINARY | rate vs day count | uncorroborated stated times | CLI finals w/o a stated time |
|---|---:|---:|---:|---:|---:|---:|
| LAX | 1812 | 21 | 11 | 1.159% | 0 | 73 |
| MDW | 1825 | 4 | 3 | 0.219% | 2 | 9 |
| MIA | 1798 | 2 | 1 | 0.111% | 0 | 11 |
| NYC | 1736 | 10 | 5 | 0.576% | 67 | 11 |
| SFO | 1793 | 18 | 3 | 1.004% | 0 | 15 |

Every implausible record (none excluded from any table above or below):

| station | climate day | issuance | CLI tmax | stated hour (LST) | ASOS day max | ASOS near stated time | reason |
|---|---|---|---:|---:|---:|---:|---|
| LAX | 2021-10-04 | FINAL | 83 | 02 | 81 | 66 | exceeds_asos_at_stated_time |
| LAX | 2021-10-04 | PRELIMINARY | 83 | 02 | 81 | 66 | exceeds_asos_at_stated_time |
| LAX | 2021-10-04 | PRELIMINARY | 83 | 02 | 81 | 66 | exceeds_asos_at_stated_time |
| LAX | 2023-09-18 | FINAL | 79 | 08 | 72 | 69 | exceeds_asos_daily_max+exceeds_asos_at_stated_time |
| LAX | 2023-09-18 | PRELIMINARY | 79 | 08 | 72 | 69 | exceeds_asos_daily_max+exceeds_asos_at_stated_time |
| LAX | 2023-10-05 | FINAL | 91 | 10 | 89 | 84 | exceeds_asos_at_stated_time |
| LAX | 2023-10-05 | PRELIMINARY | 91 | 10 | 89 | 84 | exceeds_asos_at_stated_time |
| LAX | 2023-10-05 | PRELIMINARY | 91 | 10 | 89 | 84 | exceeds_asos_at_stated_time |
| LAX | 2023-12-02 | FINAL | 71 | 12 | 66 | 65 | exceeds_asos_at_stated_time |
| LAX | 2023-12-02 | PRELIMINARY | 71 | 12 | 66 | 65 | exceeds_asos_at_stated_time |
| LAX | 2023-12-02 | PRELIMINARY | 71 | 12 | 66 | 65 | exceeds_asos_at_stated_time |
| LAX | 2024-01-30 | FINAL | 72 | 11 | 70 | 66 | exceeds_asos_at_stated_time |
| LAX | 2024-01-30 | PRELIMINARY | 72 | 11 | 70 | 66 | exceeds_asos_at_stated_time |
| LAX | 2024-02-10 | FINAL | 67 | 18 | 64 | 57 | exceeds_asos_at_stated_time |
| LAX | 2024-03-26 | FINAL | 63 | 21 | 63 | 56 | exceeds_asos_at_stated_time |
| LAX | 2024-10-18 | FINAL | 84 | 14 | 82 | 77 | exceeds_asos_at_stated_time |
| LAX | 2024-10-18 | PRELIMINARY | 84 | 14 | 82 | 77 | exceeds_asos_at_stated_time |
| LAX | 2024-11-13 | FINAL | 78 | 11 | 76 | 72 | exceeds_asos_at_stated_time |
| LAX | 2024-11-13 | PRELIMINARY | 78 | 11 | 76 | 72 | exceeds_asos_at_stated_time |
| LAX | 2025-02-27 | FINAL | 86 | 13 | 84 | 73 | exceeds_asos_at_stated_time |
| LAX | 2025-02-27 | PRELIMINARY | 86 | 13 | 84 | 73 | exceeds_asos_at_stated_time |
| MDW | 2021-12-30 | PRELIMINARY | 55 | 07 | 39 | 37 | exceeds_asos_daily_max+exceeds_asos_at_stated_time |
| MDW | 2022-11-14 | FINAL | 41 | 08 | 48 | 33 | exceeds_asos_at_stated_time |
| MDW | 2023-03-14 | PRELIMINARY | 38 | 02 | 37 | 27 | exceeds_asos_at_stated_time |
| MDW | 2023-04-01 | PRELIMINARY | 54 | 03 | 48 | 45 | exceeds_asos_daily_max+exceeds_asos_at_stated_time |
| MIA | 2022-11-23 | PRELIMINARY | 90 | 05 | 86 | 72 | exceeds_asos_at_stated_time |
| MIA | 2024-11-27 | FINAL | 84 | 04 | 81 | 67 | exceeds_asos_at_stated_time |
| NYC | 2021-03-31 | FINAL | 67 | 13 | 66 | 59 | exceeds_asos_at_stated_time |
| NYC | 2021-03-31 | PRELIMINARY | 67 | 13 | 66 | 59 | exceeds_asos_at_stated_time |
| NYC | 2021-07-08 | FINAL | 84 | 13 | 84 | 77 | exceeds_asos_at_stated_time |
| NYC | 2021-07-08 | PRELIMINARY | 84 | 13 | 84 | 77 | exceeds_asos_at_stated_time |
| NYC | 2022-07-16 | FINAL | 85 | 13 | 84 | 72 | exceeds_asos_at_stated_time |
| NYC | 2022-07-16 | PRELIMINARY | 85 | 13 | 84 | 72 | exceeds_asos_at_stated_time |
| NYC | 2025-04-01 | FINAL | 58 | 01 | 58 | 52 | exceeds_asos_at_stated_time |
| NYC | 2025-04-01 | PRELIMINARY | 58 | 01 | 58 | 52 | exceeds_asos_at_stated_time |
| NYC | 2025-09-06 | FINAL | 86 | 13 | 85 | 78 | exceeds_asos_at_stated_time |
| NYC | 2025-09-06 | PRELIMINARY | 86 | 13 | 85 | 78 | exceeds_asos_at_stated_time |
| SFO | 2021-01-05 | FINAL | 58 | 22 | 55 | 52 | exceeds_asos_at_stated_time |
| SFO | 2021-04-02 | FINAL | 70 | 13 | 63 | 61 | exceeds_asos_daily_max+exceeds_asos_at_stated_time |
| SFO | 2021-07-20 | FINAL | 66 | 21 | 66 | 59 | exceeds_asos_at_stated_time |
| SFO | 2021-07-28 | FINAL | 74 | 05 | 72 | 57 | exceeds_asos_at_stated_time |
| SFO | 2021-07-28 | PRELIMINARY | 71 | 05 | 72 | 57 | exceeds_asos_at_stated_time |
| SFO | 2021-08-03 | FINAL | 68 | 05 | 68 | 56 | exceeds_asos_at_stated_time |
| SFO | 2021-08-03 | PRELIMINARY | 70 | 05 | 68 | 56 | exceeds_asos_at_stated_time |
| SFO | 2021-08-13 | FINAL | 71 | 21 | 72 | 63 | exceeds_asos_at_stated_time |
| SFO | 2021-09-23 | FINAL | 82 | 21 | 77 | 61 | exceeds_asos_at_stated_time |
| SFO | 2021-10-24 | FINAL | 65 | 21 | 64 | 58 | exceeds_asos_at_stated_time |
| SFO | 2022-01-18 | FINAL | 60 | 22 | 55 | 50 | exceeds_asos_at_stated_time |
| SFO | 2022-01-30 | FINAL | 58 | 22 | 57 | 52 | exceeds_asos_at_stated_time |
| SFO | 2022-02-22 | FINAL | 55 | 22 | 54 | 46 | exceeds_asos_at_stated_time |
| SFO | 2023-05-12 | FINAL | 69 | 12 | 66 | 63 | exceeds_asos_at_stated_time |
| SFO | 2023-05-12 | PRELIMINARY | 69 | 12 | 66 | 63 | exceeds_asos_at_stated_time |
| SFO | 2023-11-08 | FINAL | 75 | 09 | 71 | 64 | exceeds_asos_at_stated_time |
| SFO | 2024-05-06 | FINAL | 68 | 12 | 63 | 61 | exceeds_asos_at_stated_time |
| SFO | 2024-10-30 | FINAL | 63 | 19 | 63 | 56 | exceeds_asos_at_stated_time |

## 5. Headline — first hour after which the crossing risk stays below a level

The hour from which the Wilson-95% **upper** bound on `P(M > upper_f)` stays
at or below each reference level for the rest of the climate day. `—` means
no such hour exists: the risk never gets that small before midnight. These
levels are readout points, not thresholds this study passes judgement
against or tunes toward.

### 5.0 Resolution — what this corpus can and cannot resolve

A cell with zero observed events reports a Wilson upper of exactly
`z²/(n + z²)`. That is the **resolution floor**: no reference level below it
is reachable with this corpus, however safe the physics is. Per-station,
per-season, per-headroom cells run a few hundred station-days, so levels
below roughly 1% are unreachable at that granularity — a statement about
statistical POWER, not about the hazard. §5.3 pools seasons (never
headroom) to buy resolution, at the cost of the seasonal conditioning.

| station | median cell n (per season, per headroom) | resolution floor | pooled-season cell n | pooled resolution floor |
|---|---:|---:|---:|---:|
| LAX | 227 | 1.664% | 908 | 0.421% |
| MDW | 230 | 1.643% | 920 | 0.416% |
| MIA | 225 | 1.679% | 900 | 0.425% |
| NYC | 216 | 1.747% | 864 | 0.443% |
| SFO | 222 | 1.701% | 888 | 0.431% |

### 5.1 First hour, per station × season × headroom

**basis `cli`, headroom 0**

| station | season | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% |
|---|---|---:|---:|---:|---:|
| LAX | DJF | — | — | — | — |
| LAX | MAM | — | — | — | — |
| LAX | JJA | — | — | — | — |
| LAX | SON | — | — | — | — |
| MDW | DJF | — | — | — | — |
| MDW | MAM | — | — | — | — |
| MDW | JJA | — | — | — | — |
| MDW | SON | — | — | — | — |
| MIA | DJF | — | — | — | — |
| MIA | MAM | — | — | — | — |
| MIA | JJA | — | — | — | — |
| MIA | SON | — | — | — | — |
| NYC | DJF | — | — | — | — |
| NYC | MAM | — | — | — | — |
| NYC | JJA | — | — | — | — |
| NYC | SON | — | — | — | — |
| SFO | DJF | — | — | — | — |
| SFO | MAM | — | — | — | — |
| SFO | JJA | — | — | — | — |
| SFO | SON | — | — | — | — |

**basis `cli`, headroom 1**

| station | season | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% |
|---|---|---:|---:|---:|---:|
| LAX | DJF | — | — | — | — |
| LAX | MAM | 21h | — | — | — |
| LAX | JJA | 16h | — | — | — |
| LAX | SON | — | — | — | — |
| MDW | DJF | 21h | — | — | — |
| MDW | MAM | 17h | — | — | — |
| MDW | JJA | 15h | — | — | — |
| MDW | SON | 16h | — | — | — |
| MIA | DJF | 22h | — | — | — |
| MIA | MAM | 14h | — | — | — |
| MIA | JJA | 14h | — | — | — |
| MIA | SON | 13h | — | — | — |
| NYC | DJF | — | — | — | — |
| NYC | MAM | — | — | — | — |
| NYC | JJA | — | — | — | — |
| NYC | SON | — | — | — | — |
| SFO | DJF | 21h | — | — | — |
| SFO | MAM | 15h | — | — | — |
| SFO | JJA | 14h | — | — | — |
| SFO | SON | 15h | — | — | — |

**basis `obs`, headroom 0**

| station | season | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% |
|---|---|---:|---:|---:|---:|
| LAX | DJF | 15h | — | — | — |
| LAX | MAM | 15h | — | — | — |
| LAX | JJA | 13h | — | — | — |
| LAX | SON | 13h | — | — | — |
| MDW | DJF | 23h | — | — | — |
| MDW | MAM | 18h | — | — | — |
| MDW | JJA | 16h | — | — | — |
| MDW | SON | 17h | — | — | — |
| MIA | DJF | 15h | — | — | — |
| MIA | MAM | 15h | — | — | — |
| MIA | JJA | 14h | — | — | — |
| MIA | SON | 15h | — | — | — |
| NYC | DJF | 23h | — | — | — |
| NYC | MAM | 21h | — | — | — |
| NYC | JJA | 16h | — | — | — |
| NYC | SON | 21h | — | — | — |
| SFO | DJF | 17h | — | — | — |
| SFO | MAM | 15h | — | — | — |
| SFO | JJA | 15h | — | — | — |
| SFO | SON | 16h | — | — | — |

**basis `obs`, headroom 1**

| station | season | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% |
|---|---|---:|---:|---:|---:|
| LAX | DJF | 18h | — | — | — |
| LAX | MAM | 13h | — | — | — |
| LAX | JJA | 14h | — | — | — |
| LAX | SON | 14h | — | — | — |
| MDW | DJF | 22h | — | — | — |
| MDW | MAM | 16h | — | — | — |
| MDW | JJA | 15h | — | — | — |
| MDW | SON | 16h | — | — | — |
| MIA | DJF | 15h | — | — | — |
| MIA | MAM | 14h | — | — | — |
| MIA | JJA | 14h | — | — | — |
| MIA | SON | 14h | — | — | — |
| NYC | DJF | 22h | — | — | — |
| NYC | MAM | 19h | — | — | — |
| NYC | JJA | 15h | — | — | — |
| NYC | SON | 15h | — | — | — |
| SFO | DJF | 19h | — | — | — |
| SFO | MAM | 14h | — | — | — |
| SFO | JJA | 14h | — | — | — |
| SFO | SON | 15h | — | — | — |

### 5.2 End-of-day decomposition — is the residual risk weather, or the instrument?

At hour 23 the climate day is physically OVER: on the `obs` basis
`R(23) == M` by construction, so every `obs` crossing count here is exactly
zero. Anything left on the `cli` basis at hour 23 is therefore NOT late-day
weather — it is the METAR↔CLI instrument basis of §2 landing the settled
integer outside a rung the observations never left.

| station | season | headroom | n | cross rate @23h | of which physics | of which basis-only | cross Wilson-95 UPPER @23h |
|---|---|---:|---:|---:|---:|---:|---:|
| LAX | DJF | 0 | 246 | 15.041% | 0.000% | 15.041% | 20.043% |
| LAX | DJF | 1 | 201 | 4.975% | 0.000% | 4.975% | 8.914% |
| LAX | MAM | 0 | 209 | 16.268% | 0.000% | 16.268% | 21.872% |
| LAX | MAM | 1 | 250 | 2.000% | 0.000% | 2.000% | 4.596% |
| LAX | JJA | 0 | 240 | 36.667% | 0.000% | 36.667% | 42.929% |
| LAX | JJA | 1 | 215 | 1.860% | 0.000% | 1.860% | 4.685% |
| LAX | SON | 0 | 194 | 29.381% | 0.000% | 29.381% | 36.142% |
| LAX | SON | 1 | 257 | 3.891% | 0.000% | 3.891% | 7.013% |
| MDW | DJF | 0 | 204 | 8.824% | 0.000% | 8.824% | 13.515% |
| MDW | DJF | 1 | 247 | 0.000% | 0.000% | 0.000% | 1.531% |
| MDW | MAM | 0 | 229 | 19.214% | 0.000% | 19.214% | 24.808% |
| MDW | MAM | 1 | 231 | 0.866% | 0.000% | 0.866% | 3.101% |
| MDW | JJA | 0 | 224 | 19.196% | 0.000% | 19.196% | 24.856% |
| MDW | JJA | 1 | 235 | 0.426% | 0.000% | 0.426% | 2.371% |
| MDW | SON | 0 | 190 | 11.579% | 0.000% | 11.579% | 16.909% |
| MDW | SON | 1 | 265 | 0.377% | 0.000% | 0.377% | 2.106% |
| MIA | DJF | 0 | 230 | 15.652% | 0.000% | 15.652% | 20.908% |
| MIA | DJF | 1 | 220 | 1.818% | 0.000% | 1.818% | 4.581% |
| MIA | MAM | 0 | 158 | 25.316% | 0.000% | 25.316% | 32.627% |
| MIA | MAM | 1 | 292 | 0.685% | 0.000% | 0.685% | 2.463% |
| MIA | JJA | 0 | 227 | 37.445% | 0.000% | 37.445% | 43.901% |
| MIA | JJA | 1 | 223 | 0.000% | 0.000% | 0.000% | 1.693% |
| MIA | SON | 0 | 168 | 26.190% | 0.000% | 26.190% | 33.318% |
| MIA | SON | 1 | 280 | 0.000% | 0.000% | 0.000% | 1.353% |
| NYC | DJF | 0 | 205 | 40.488% | 0.000% | 40.488% | 47.322% |
| NYC | DJF | 1 | 216 | 2.315% | 0.000% | 2.315% | 5.303% |
| NYC | MAM | 0 | 226 | 64.159% | 0.000% | 64.159% | 70.127% |
| NYC | MAM | 1 | 205 | 10.244% | 0.000% | 10.244% | 15.152% |
| NYC | JJA | 0 | 236 | 65.254% | 0.000% | 65.254% | 71.041% |
| NYC | JJA | 1 | 210 | 14.286% | 0.000% | 14.286% | 19.661% |
| NYC | SON | 0 | 214 | 47.196% | 0.000% | 47.196% | 53.875% |
| NYC | SON | 1 | 224 | 5.357% | 0.000% | 5.357% | 9.129% |
| SFO | DJF | 0 | 275 | 21.091% | 0.000% | 21.091% | 26.294% |
| SFO | DJF | 1 | 170 | 0.000% | 0.000% | 0.000% | 2.210% |
| SFO | MAM | 0 | 239 | 17.573% | 0.000% | 17.573% | 22.900% |
| SFO | MAM | 1 | 213 | 1.408% | 0.000% | 1.408% | 4.058% |
| SFO | JJA | 0 | 163 | 26.380% | 0.000% | 26.380% | 33.633% |
| SFO | JJA | 1 | 283 | 1.060% | 0.000% | 1.060% | 3.070% |
| SFO | SON | 0 | 198 | 23.737% | 0.000% | 23.737% | 30.128% |
| SFO | SON | 1 | 252 | 0.000% | 0.000% | 0.000% | 1.501% |

### 5.3 Season-pooled (headroom still never pooled)

Four times the denominator, at the cost of the seasonal conditioning that
§4 shows to matter (MDW/NYC winters are the late-peak seasons). Reported
because §5.0 shows the per-season cells cannot resolve below ~1%; NOT a
replacement for §5.1.

**basis `cli`**

| station | headroom | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% | cross rate @23h | n @23h | resolution floor @23h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | 0 | — | — | — | — | 24.297% | 889 | 0.430% |
| LAX | 1 | 18h | — | — | — | 3.142% | 923 | 0.414% |
| MDW | 0 | — | — | — | — | 14.994% | 847 | 0.451% |
| MDW | 1 | 16h | — | — | — | 0.409% | 978 | 0.391% |
| MIA | 0 | — | — | — | — | 26.181% | 783 | 0.488% |
| MIA | 1 | 14h | — | — | — | 0.591% | 1015 | 0.377% |
| NYC | 0 | — | — | — | — | 54.824% | 881 | 0.434% |
| NYC | 1 | — | — | — | — | 7.953% | 855 | 0.447% |
| SFO | 0 | — | — | — | — | 21.714% | 875 | 0.437% |
| SFO | 1 | 15h | — | — | — | 0.654% | 918 | 0.417% |

**basis `obs`**

| station | headroom | ≤5.000% | ≤1.000% | ≤0.500% | ≤0.100% | cross rate @23h | n @23h | resolution floor @23h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | 0 | 14h | 20h | 23h | — | 0.000% | 891 | 0.429% |
| LAX | 1 | 14h | 19h | 21h | — | 0.000% | 927 | 0.413% |
| MDW | 0 | 18h | 23h | 23h | — | 0.000% | 847 | 0.451% |
| MDW | 1 | 16h | 22h | 23h | — | 0.000% | 978 | 0.391% |
| MIA | 0 | 15h | 16h | 21h | — | 0.000% | 787 | 0.486% |
| MIA | 1 | 14h | 16h | 22h | — | 0.000% | 1021 | 0.375% |
| NYC | 0 | 19h | 23h | 23h | — | 0.000% | 883 | 0.433% |
| NYC | 1 | 15h | 22h | 23h | — | 0.000% | 857 | 0.446% |
| SFO | 0 | 15h | 23h | 23h | — | 0.000% | 889 | 0.430% |
| SFO | 1 | 15h | 20h | 22h | — | 0.000% | 931 | 0.411% |

## 6. Conditional on an exceedance, how big is the late rise?

`M − R(t)` restricted to cases where `M > R(t)`, per station and headroom,
capped at ≥6°F. The crossing column is the share of those exceedances that
actually left the rung — the quantity that matters.

| basis | station | headroom | exceedances | +1 | +2 | +3 | +4 | +5 | ≥6 | crossing share of exceedances |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cli | LAX | 0 | 13648 | 3222 | 1017 | 726 | 760 | 798 | 7125 | 100.000% |
| cli | LAX | 1 | 12292 | 3434 | 917 | 757 | 605 | 662 | 5917 | 72.063% |
| cli | MDW | 0 | 12156 | 2529 | 933 | 961 | 691 | 602 | 6440 | 100.000% |
| cli | MDW | 1 | 12578 | 2866 | 1098 | 835 | 865 | 639 | 6275 | 77.214% |
| cli | MIA | 0 | 13716 | 3026 | 919 | 563 | 645 | 678 | 7885 | 100.000% |
| cli | MIA | 1 | 12962 | 3934 | 1054 | 760 | 600 | 599 | 6015 | 69.650% |
| cli | NYC | 0 | 16204 | 5576 | 1901 | 897 | 820 | 698 | 6312 | 100.000% |
| cli | NYC | 1 | 16710 | 5774 | 1743 | 1005 | 737 | 740 | 6711 | 65.446% |
| cli | SFO | 0 | 12975 | 2615 | 819 | 665 | 602 | 790 | 7484 | 100.000% |
| cli | SFO | 1 | 13918 | 3025 | 776 | 747 | 829 | 831 | 7710 | 78.266% |
| obs | LAX | 0 | 10764 | 513 | 920 | 707 | 705 | 859 | 7060 | 100.000% |
| obs | LAX | 1 | 9109 | 540 | 839 | 637 | 520 | 672 | 5901 | 94.072% |
| obs | MDW | 0 | 10524 | 811 | 1119 | 798 | 694 | 604 | 6498 | 100.000% |
| obs | MDW | 1 | 10540 | 705 | 1290 | 730 | 855 | 585 | 6375 | 93.311% |
| obs | MIA | 0 | 11149 | 641 | 762 | 695 | 447 | 876 | 7728 | 100.000% |
| obs | MIA | 1 | 9692 | 626 | 1243 | 613 | 605 | 594 | 6011 | 93.541% |
| obs | NYC | 0 | 10162 | 1097 | 914 | 768 | 753 | 760 | 5870 | 100.000% |
| obs | NYC | 1 | 10583 | 1100 | 955 | 754 | 669 | 775 | 6330 | 89.606% |
| obs | SFO | 0 | 10917 | 451 | 950 | 536 | 577 | 756 | 7647 | 100.000% |
| obs | SFO | 1 | 11573 | 573 | 851 | 831 | 598 | 1010 | 7710 | 95.049% |

## 7. Full conditional table

Every cell, every denominator. `cross` is the PRIMARY quantity
(`M > upper_f`); `exceed` is the secondary (`M > R(t)`); `neg-basis` counts
days where the settled value came in below `R(t)` — possible on the `cli`
basis only, and never counted as a crossing.

### 7.1 basis `cli`

| station | season | hour | headroom | n | cross | cross rate | cross Wilson-95 UPPER | of which physics | of which basis-only | exceed | exceed rate | exceed Wilson-95 UPPER | neg-basis | resolution floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | DJF | 00 | 0 | 253 | 246 | 97.233% | 98.653% | 246 | 0 | 246 | 97.233% | 98.653% | 2 | 1.496% |
| LAX | DJF | 00 | 1 | 194 | 187 | 96.392% | 98.241% | 187 | 0 | 188 | 96.907% | 98.575% | 0 | 1.942% |
| LAX | DJF | 01 | 0 | 259 | 252 | 97.297% | 98.685% | 252 | 0 | 252 | 97.297% | 98.685% | 2 | 1.462% |
| LAX | DJF | 01 | 1 | 188 | 181 | 96.277% | 98.185% | 181 | 0 | 182 | 96.809% | 98.529% | 0 | 2.002% |
| LAX | DJF | 02 | 0 | 256 | 249 | 97.266% | 98.669% | 249 | 0 | 249 | 97.266% | 98.669% | 2 | 1.478% |
| LAX | DJF | 02 | 1 | 191 | 184 | 96.335% | 98.214% | 183 | 1 | 185 | 96.859% | 98.552% | 0 | 1.972% |
| LAX | DJF | 03 | 0 | 254 | 247 | 97.244% | 98.659% | 247 | 0 | 247 | 97.244% | 98.659% | 2 | 1.490% |
| LAX | DJF | 03 | 1 | 193 | 185 | 95.855% | 97.885% | 184 | 1 | 186 | 96.373% | 98.232% | 0 | 1.952% |
| LAX | DJF | 04 | 0 | 252 | 245 | 97.222% | 98.648% | 245 | 0 | 245 | 97.222% | 98.648% | 2 | 1.501% |
| LAX | DJF | 04 | 1 | 195 | 187 | 95.897% | 97.907% | 186 | 1 | 188 | 96.410% | 98.250% | 0 | 1.932% |
| LAX | DJF | 05 | 0 | 249 | 242 | 97.189% | 98.632% | 242 | 0 | 242 | 97.189% | 98.632% | 2 | 1.519% |
| LAX | DJF | 05 | 1 | 198 | 190 | 95.960% | 97.939% | 189 | 1 | 191 | 96.465% | 98.277% | 0 | 1.903% |
| LAX | DJF | 06 | 0 | 250 | 243 | 97.200% | 98.637% | 243 | 0 | 243 | 97.200% | 98.637% | 2 | 1.513% |
| LAX | DJF | 06 | 1 | 197 | 189 | 95.939% | 97.928% | 188 | 1 | 190 | 96.447% | 98.268% | 0 | 1.913% |
| LAX | DJF | 07 | 0 | 247 | 239 | 96.761% | 98.350% | 239 | 0 | 239 | 96.761% | 98.350% | 3 | 1.531% |
| LAX | DJF | 07 | 1 | 200 | 191 | 95.500% | 97.615% | 190 | 1 | 192 | 96.000% | 97.959% | 0 | 1.885% |
| LAX | DJF | 08 | 0 | 263 | 254 | 96.578% | 98.189% | 253 | 1 | 254 | 96.578% | 98.189% | 3 | 1.440% |
| LAX | DJF | 08 | 1 | 184 | 175 | 95.109% | 97.406% | 175 | 0 | 176 | 95.652% | 97.781% | 0 | 2.045% |
| LAX | DJF | 09 | 0 | 290 | 275 | 94.828% | 96.841% | 274 | 1 | 275 | 94.828% | 96.841% | 4 | 1.307% |
| LAX | DJF | 09 | 1 | 157 | 141 | 89.809% | 93.629% | 142 | 1 | 149 | 94.904% | 97.396% | 0 | 2.388% |
| LAX | DJF | 10 | 0 | 275 | 223 | 81.091% | 85.279% | 218 | 5 | 223 | 81.091% | 85.279% | 12 | 1.378% |
| LAX | DJF | 10 | 1 | 172 | 118 | 68.605% | 75.070% | 113 | 12 | 147 | 85.465% | 89.957% | 1 | 2.185% |
| LAX | DJF | 11 | 0 | 250 | 134 | 53.600% | 59.681% | 117 | 18 | 134 | 53.600% | 59.681% | 34 | 1.513% |
| LAX | DJF | 11 | 1 | 197 | 71 | 36.041% | 42.953% | 65 | 15 | 135 | 68.528% | 74.606% | 7 | 1.913% |
| LAX | DJF | 12 | 0 | 236 | 79 | 33.475% | 39.717% | 49 | 30 | 79 | 33.475% | 39.717% | 48 | 1.602% |
| LAX | DJF | 12 | 1 | 211 | 39 | 18.483% | 24.268% | 34 | 14 | 115 | 54.502% | 61.081% | 17 | 1.788% |
| LAX | DJF | 13 | 0 | 245 | 60 | 24.490% | 30.241% | 27 | 33 | 60 | 24.490% | 30.241% | 52 | 1.544% |
| LAX | DJF | 13 | 1 | 202 | 24 | 11.881% | 17.070% | 15 | 12 | 83 | 41.089% | 47.979% | 23 | 1.866% |
| LAX | DJF | 14 | 0 | 243 | 45 | 18.519% | 23.879% | 9 | 36 | 45 | 18.519% | 23.879% | 56 | 1.556% |
| LAX | DJF | 14 | 1 | 204 | 17 | 8.333% | 12.939% | 8 | 10 | 72 | 35.294% | 42.068% | 26 | 1.848% |
| LAX | DJF | 15 | 0 | 244 | 41 | 16.803% | 22.001% | 5 | 36 | 41 | 16.803% | 22.001% | 58 | 1.550% |
| LAX | DJF | 15 | 1 | 203 | 15 | 7.389% | 11.832% | 5 | 10 | 69 | 33.990% | 40.750% | 27 | 1.857% |
| LAX | DJF | 16 | 0 | 245 | 40 | 16.327% | 21.468% | 4 | 36 | 40 | 16.327% | 21.468% | 59 | 1.544% |
| LAX | DJF | 16 | 1 | 202 | 14 | 6.931% | 11.296% | 4 | 10 | 67 | 33.168% | 39.922% | 27 | 1.866% |
| LAX | DJF | 17 | 0 | 245 | 39 | 15.918% | 21.020% | 3 | 36 | 39 | 15.918% | 21.020% | 59 | 1.544% |
| LAX | DJF | 17 | 1 | 202 | 15 | 7.426% | 11.889% | 5 | 10 | 67 | 33.168% | 39.922% | 27 | 1.866% |
| LAX | DJF | 18 | 0 | 246 | 40 | 16.260% | 21.384% | 4 | 36 | 40 | 16.260% | 21.384% | 59 | 1.538% |
| LAX | DJF | 18 | 1 | 201 | 13 | 6.468% | 10.750% | 3 | 10 | 66 | 32.836% | 39.597% | 27 | 1.875% |
| LAX | DJF | 19 | 0 | 249 | 41 | 16.466% | 21.575% | 4 | 37 | 41 | 16.466% | 21.575% | 59 | 1.519% |
| LAX | DJF | 19 | 1 | 198 | 11 | 5.556% | 9.673% | 1 | 10 | 63 | 31.818% | 38.599% | 27 | 1.903% |
| LAX | DJF | 20 | 0 | 248 | 40 | 16.129% | 21.217% | 3 | 37 | 40 | 16.129% | 21.217% | 59 | 1.525% |
| LAX | DJF | 20 | 1 | 199 | 10 | 5.025% | 9.002% | 0 | 10 | 62 | 31.156% | 37.896% | 27 | 1.894% |
| LAX | DJF | 21 | 0 | 247 | 39 | 15.789% | 20.856% | 2 | 37 | 39 | 15.789% | 20.856% | 59 | 1.531% |
| LAX | DJF | 21 | 1 | 200 | 10 | 5.000% | 8.958% | 0 | 10 | 62 | 31.000% | 37.717% | 27 | 1.885% |
| LAX | DJF | 22 | 0 | 246 | 38 | 15.447% | 20.491% | 1 | 37 | 38 | 15.447% | 20.491% | 59 | 1.538% |
| LAX | DJF | 22 | 1 | 201 | 10 | 4.975% | 8.914% | 0 | 10 | 62 | 30.846% | 37.540% | 27 | 1.875% |
| LAX | DJF | 23 | 0 | 246 | 37 | 15.041% | 20.043% | 0 | 37 | 37 | 15.041% | 20.043% | 60 | 1.538% |
| LAX | DJF | 23 | 1 | 201 | 10 | 4.975% | 8.914% | 0 | 10 | 62 | 30.846% | 37.540% | 27 | 1.875% |
| LAX | JJA | 00 | 0 | 204 | 204 | 100.000% | 100.000% | 204 | 0 | 204 | 100.000% | 100.000% | 0 | 1.848% |
| LAX | JJA | 00 | 1 | 251 | 251 | 100.000% | 100.000% | 251 | 0 | 251 | 100.000% | 100.000% | 0 | 1.507% |
| LAX | JJA | 01 | 0 | 198 | 198 | 100.000% | 100.000% | 198 | 0 | 198 | 100.000% | 100.000% | 0 | 1.903% |
| LAX | JJA | 01 | 1 | 257 | 257 | 100.000% | 100.000% | 257 | 0 | 257 | 100.000% | 100.000% | 0 | 1.473% |
| LAX | JJA | 02 | 0 | 196 | 196 | 100.000% | 100.000% | 196 | 0 | 196 | 100.000% | 100.000% | 0 | 1.922% |
| LAX | JJA | 02 | 1 | 259 | 259 | 100.000% | 100.000% | 259 | 0 | 259 | 100.000% | 100.000% | 0 | 1.462% |
| LAX | JJA | 03 | 0 | 204 | 204 | 100.000% | 100.000% | 204 | 0 | 204 | 100.000% | 100.000% | 0 | 1.848% |
| LAX | JJA | 03 | 1 | 251 | 251 | 100.000% | 100.000% | 251 | 0 | 251 | 100.000% | 100.000% | 0 | 1.507% |
| LAX | JJA | 04 | 0 | 206 | 206 | 100.000% | 100.000% | 206 | 0 | 206 | 100.000% | 100.000% | 0 | 1.831% |
| LAX | JJA | 04 | 1 | 249 | 248 | 99.598% | 99.929% | 248 | 0 | 249 | 100.000% | 100.000% | 0 | 1.519% |
| LAX | JJA | 05 | 0 | 206 | 205 | 99.515% | 99.914% | 205 | 0 | 205 | 99.515% | 99.914% | 0 | 1.831% |
| LAX | JJA | 05 | 1 | 249 | 249 | 100.000% | 100.000% | 249 | 0 | 249 | 100.000% | 100.000% | 0 | 1.519% |
| LAX | JJA | 06 | 0 | 184 | 183 | 99.457% | 99.904% | 183 | 0 | 183 | 99.457% | 99.904% | 0 | 2.045% |
| LAX | JJA | 06 | 1 | 271 | 271 | 100.000% | 100.000% | 271 | 0 | 271 | 100.000% | 100.000% | 0 | 1.398% |
| LAX | JJA | 07 | 0 | 151 | 150 | 99.338% | 99.883% | 150 | 0 | 150 | 99.338% | 99.883% | 0 | 2.481% |
| LAX | JJA | 07 | 1 | 304 | 299 | 98.355% | 99.295% | 297 | 3 | 303 | 99.671% | 99.942% | 0 | 1.248% |
| LAX | JJA | 08 | 0 | 168 | 156 | 92.857% | 95.867% | 143 | 13 | 156 | 92.857% | 95.867% | 0 | 2.235% |
| LAX | JJA | 08 | 1 | 287 | 248 | 86.411% | 89.898% | 244 | 17 | 275 | 95.819% | 97.592% | 0 | 1.321% |
| LAX | JJA | 09 | 0 | 192 | 161 | 83.854% | 88.386% | 124 | 37 | 161 | 83.854% | 88.386% | 4 | 1.962% |
| LAX | JJA | 09 | 1 | 263 | 168 | 63.878% | 69.445% | 162 | 21 | 220 | 83.650% | 87.629% | 7 | 1.440% |
| LAX | JJA | 10 | 0 | 199 | 139 | 69.849% | 75.800% | 85 | 54 | 139 | 69.849% | 75.800% | 10 | 1.894% |
| LAX | JJA | 10 | 1 | 256 | 104 | 40.625% | 46.737% | 100 | 25 | 175 | 68.359% | 73.749% | 14 | 1.478% |
| LAX | JJA | 11 | 0 | 223 | 132 | 59.193% | 65.435% | 59 | 73 | 132 | 59.193% | 65.435% | 13 | 1.693% |
| LAX | JJA | 11 | 1 | 232 | 41 | 17.672% | 23.095% | 45 | 13 | 109 | 46.983% | 53.402% | 26 | 1.629% |
| LAX | JJA | 12 | 0 | 231 | 110 | 47.619% | 54.046% | 25 | 85 | 110 | 47.619% | 54.046% | 18 | 1.636% |
| LAX | JJA | 12 | 1 | 224 | 12 | 5.357% | 9.129% | 19 | 4 | 69 | 30.804% | 37.131% | 39 | 1.686% |
| LAX | JJA | 13 | 0 | 235 | 92 | 39.149% | 45.516% | 5 | 87 | 92 | 39.149% | 45.516% | 24 | 1.608% |
| LAX | JJA | 13 | 1 | 220 | 8 | 3.636% | 7.010% | 9 | 4 | 49 | 22.273% | 28.220% | 45 | 1.716% |
| LAX | JJA | 14 | 0 | 237 | 88 | 37.131% | 43.441% | 0 | 88 | 88 | 37.131% | 43.441% | 24 | 1.595% |
| LAX | JJA | 14 | 1 | 218 | 5 | 2.294% | 5.256% | 1 | 4 | 37 | 16.972% | 22.517% | 51 | 1.732% |
| LAX | JJA | 15 | 0 | 239 | 88 | 36.820% | 43.098% | 0 | 88 | 88 | 36.820% | 43.098% | 24 | 1.582% |
| LAX | JJA | 15 | 1 | 216 | 5 | 2.315% | 5.303% | 1 | 4 | 35 | 16.204% | 21.701% | 51 | 1.747% |
| LAX | JJA | 16 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 16 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 17 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 17 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 18 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 18 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 19 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 19 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 20 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 20 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 21 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 21 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 22 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 22 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | JJA | 23 | 0 | 240 | 88 | 36.667% | 42.929% | 0 | 88 | 88 | 36.667% | 42.929% | 24 | 1.575% |
| LAX | JJA | 23 | 1 | 215 | 4 | 1.860% | 4.685% | 0 | 4 | 33 | 15.349% | 20.771% | 51 | 1.755% |
| LAX | MAM | 00 | 0 | 300 | 300 | 100.000% | 100.000% | 299 | 1 | 300 | 100.000% | 100.000% | 0 | 1.264% |
| LAX | MAM | 00 | 1 | 159 | 157 | 98.742% | 99.654% | 157 | 0 | 159 | 100.000% | 100.000% | 0 | 2.359% |
| LAX | MAM | 01 | 0 | 298 | 298 | 100.000% | 100.000% | 297 | 1 | 298 | 100.000% | 100.000% | 0 | 1.273% |
| LAX | MAM | 01 | 1 | 161 | 158 | 98.137% | 99.364% | 158 | 0 | 160 | 99.379% | 99.890% | 0 | 2.330% |
| LAX | MAM | 02 | 0 | 296 | 296 | 100.000% | 100.000% | 295 | 1 | 296 | 100.000% | 100.000% | 0 | 1.281% |
| LAX | MAM | 02 | 1 | 163 | 159 | 97.546% | 99.042% | 159 | 0 | 162 | 99.387% | 99.892% | 0 | 2.302% |
| LAX | MAM | 03 | 0 | 296 | 295 | 99.662% | 99.940% | 294 | 1 | 295 | 99.662% | 99.940% | 0 | 1.281% |
| LAX | MAM | 03 | 1 | 163 | 159 | 97.546% | 99.042% | 159 | 0 | 162 | 99.387% | 99.892% | 0 | 2.302% |
| LAX | MAM | 04 | 0 | 300 | 298 | 99.333% | 99.817% | 297 | 1 | 298 | 99.333% | 99.817% | 0 | 1.264% |
| LAX | MAM | 04 | 1 | 159 | 156 | 98.113% | 99.356% | 156 | 0 | 158 | 99.371% | 99.889% | 0 | 2.359% |
| LAX | MAM | 05 | 0 | 299 | 296 | 98.997% | 99.658% | 295 | 1 | 296 | 98.997% | 99.658% | 0 | 1.268% |
| LAX | MAM | 05 | 1 | 160 | 157 | 98.125% | 99.360% | 157 | 0 | 159 | 99.375% | 99.890% | 0 | 2.345% |
| LAX | MAM | 06 | 0 | 296 | 293 | 98.986% | 99.655% | 292 | 1 | 293 | 98.986% | 99.655% | 0 | 1.281% |
| LAX | MAM | 06 | 1 | 163 | 160 | 98.160% | 99.372% | 160 | 0 | 162 | 99.387% | 99.892% | 0 | 2.302% |
| LAX | MAM | 07 | 0 | 320 | 317 | 99.062% | 99.681% | 316 | 1 | 317 | 99.062% | 99.681% | 0 | 1.186% |
| LAX | MAM | 07 | 1 | 139 | 135 | 97.122% | 98.875% | 135 | 0 | 138 | 99.281% | 99.873% | 0 | 2.689% |
| LAX | MAM | 08 | 0 | 295 | 288 | 97.627% | 98.846% | 285 | 3 | 288 | 97.627% | 98.846% | 1 | 1.285% |
| LAX | MAM | 08 | 1 | 164 | 140 | 85.366% | 89.965% | 145 | 2 | 161 | 98.171% | 99.376% | 1 | 2.289% |
| LAX | MAM | 09 | 0 | 271 | 242 | 89.299% | 92.445% | 233 | 9 | 242 | 89.299% | 92.445% | 3 | 1.398% |
| LAX | MAM | 09 | 1 | 188 | 128 | 68.085% | 74.329% | 123 | 13 | 166 | 88.298% | 92.144% | 6 | 2.002% |
| LAX | MAM | 10 | 0 | 259 | 193 | 74.517% | 79.439% | 169 | 24 | 193 | 74.517% | 79.439% | 12 | 1.462% |
| LAX | MAM | 10 | 1 | 200 | 75 | 37.500% | 44.386% | 75 | 7 | 139 | 69.500% | 75.464% | 11 | 1.885% |
| LAX | MAM | 11 | 0 | 226 | 107 | 47.345% | 53.845% | 80 | 27 | 107 | 47.345% | 53.845% | 32 | 1.671% |
| LAX | MAM | 11 | 1 | 233 | 36 | 15.451% | 20.648% | 39 | 9 | 123 | 52.790% | 59.102% | 18 | 1.622% |
| LAX | MAM | 12 | 0 | 216 | 67 | 31.019% | 37.474% | 37 | 30 | 67 | 31.019% | 37.474% | 42 | 1.747% |
| LAX | MAM | 12 | 1 | 243 | 17 | 6.996% | 10.917% | 14 | 7 | 95 | 39.095% | 45.354% | 28 | 1.556% |
| LAX | MAM | 13 | 0 | 213 | 43 | 20.188% | 26.085% | 10 | 33 | 43 | 20.188% | 26.085% | 50 | 1.772% |
| LAX | MAM | 13 | 1 | 246 | 8 | 3.252% | 6.285% | 3 | 5 | 78 | 31.707% | 37.766% | 32 | 1.538% |
| LAX | MAM | 14 | 0 | 211 | 38 | 18.009% | 23.752% | 5 | 33 | 38 | 18.009% | 23.752% | 52 | 1.788% |
| LAX | MAM | 14 | 1 | 248 | 7 | 2.823% | 5.711% | 2 | 5 | 76 | 30.645% | 36.642% | 32 | 1.525% |
| LAX | MAM | 15 | 0 | 211 | 37 | 17.536% | 23.234% | 3 | 34 | 37 | 17.536% | 23.234% | 53 | 1.788% |
| LAX | MAM | 15 | 1 | 248 | 6 | 2.419% | 5.177% | 1 | 5 | 75 | 30.242% | 36.224% | 32 | 1.525% |
| LAX | MAM | 16 | 0 | 211 | 37 | 17.536% | 23.234% | 3 | 34 | 37 | 17.536% | 23.234% | 53 | 1.788% |
| LAX | MAM | 16 | 1 | 248 | 6 | 2.419% | 5.177% | 1 | 5 | 75 | 30.242% | 36.224% | 32 | 1.525% |
| LAX | MAM | 17 | 0 | 211 | 36 | 17.062% | 22.715% | 2 | 34 | 36 | 17.062% | 22.715% | 53 | 1.788% |
| LAX | MAM | 17 | 1 | 248 | 6 | 2.419% | 5.177% | 1 | 5 | 75 | 30.242% | 36.224% | 32 | 1.525% |
| LAX | MAM | 18 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 18 | 1 | 250 | 6 | 2.400% | 5.136% | 1 | 5 | 75 | 30.000% | 35.948% | 32 | 1.513% |
| LAX | MAM | 19 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 19 | 1 | 250 | 6 | 2.400% | 5.136% | 1 | 5 | 75 | 30.000% | 35.948% | 32 | 1.513% |
| LAX | MAM | 20 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 20 | 1 | 250 | 6 | 2.400% | 5.136% | 1 | 5 | 75 | 30.000% | 35.948% | 32 | 1.513% |
| LAX | MAM | 21 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 21 | 1 | 250 | 5 | 2.000% | 4.596% | 0 | 5 | 74 | 29.600% | 35.533% | 33 | 1.513% |
| LAX | MAM | 22 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 22 | 1 | 250 | 5 | 2.000% | 4.596% | 0 | 5 | 74 | 29.600% | 35.533% | 33 | 1.513% |
| LAX | MAM | 23 | 0 | 209 | 34 | 16.268% | 21.872% | 0 | 34 | 34 | 16.268% | 21.872% | 53 | 1.805% |
| LAX | MAM | 23 | 1 | 250 | 5 | 2.000% | 4.596% | 0 | 5 | 74 | 29.600% | 35.533% | 33 | 1.513% |
| LAX | SON | 00 | 0 | 253 | 251 | 99.209% | 99.783% | 251 | 0 | 251 | 99.209% | 99.783% | 0 | 1.496% |
| LAX | SON | 00 | 1 | 198 | 197 | 99.495% | 99.911% | 197 | 0 | 197 | 99.495% | 99.911% | 0 | 1.903% |
| LAX | SON | 01 | 0 | 256 | 254 | 99.219% | 99.785% | 254 | 0 | 254 | 99.219% | 99.785% | 0 | 1.478% |
| LAX | SON | 01 | 1 | 195 | 194 | 99.487% | 99.909% | 194 | 0 | 194 | 99.487% | 99.909% | 0 | 1.932% |
| LAX | SON | 02 | 0 | 262 | 260 | 99.237% | 99.790% | 260 | 0 | 260 | 99.237% | 99.790% | 0 | 1.445% |
| LAX | SON | 02 | 1 | 189 | 188 | 99.471% | 99.907% | 188 | 0 | 188 | 99.471% | 99.907% | 0 | 1.992% |
| LAX | SON | 03 | 0 | 262 | 260 | 99.237% | 99.790% | 260 | 0 | 260 | 99.237% | 99.790% | 0 | 1.445% |
| LAX | SON | 03 | 1 | 189 | 188 | 99.471% | 99.907% | 188 | 0 | 188 | 99.471% | 99.907% | 0 | 1.992% |
| LAX | SON | 04 | 0 | 258 | 256 | 99.225% | 99.787% | 256 | 0 | 256 | 99.225% | 99.787% | 0 | 1.467% |
| LAX | SON | 04 | 1 | 193 | 192 | 99.482% | 99.908% | 192 | 0 | 192 | 99.482% | 99.908% | 0 | 1.952% |
| LAX | SON | 05 | 0 | 261 | 259 | 99.234% | 99.790% | 259 | 0 | 259 | 99.234% | 99.790% | 0 | 1.450% |
| LAX | SON | 05 | 1 | 190 | 189 | 99.474% | 99.907% | 189 | 0 | 189 | 99.474% | 99.907% | 0 | 1.982% |
| LAX | SON | 06 | 0 | 256 | 254 | 99.219% | 99.785% | 254 | 0 | 254 | 99.219% | 99.785% | 0 | 1.478% |
| LAX | SON | 06 | 1 | 195 | 193 | 98.974% | 99.718% | 193 | 0 | 193 | 98.974% | 99.718% | 0 | 1.932% |
| LAX | SON | 07 | 0 | 229 | 226 | 98.690% | 99.553% | 226 | 0 | 226 | 98.690% | 99.553% | 0 | 1.650% |
| LAX | SON | 07 | 1 | 222 | 219 | 98.649% | 99.539% | 220 | 0 | 220 | 99.099% | 99.753% | 0 | 1.701% |
| LAX | SON | 08 | 0 | 215 | 212 | 98.605% | 99.524% | 211 | 1 | 212 | 98.605% | 99.524% | 0 | 1.755% |
| LAX | SON | 08 | 1 | 236 | 228 | 96.610% | 98.272% | 231 | 1 | 233 | 98.729% | 99.567% | 0 | 1.602% |
| LAX | SON | 09 | 0 | 188 | 171 | 90.957% | 94.278% | 159 | 12 | 171 | 90.957% | 94.278% | 6 | 2.002% |
| LAX | SON | 09 | 1 | 263 | 194 | 73.764% | 78.711% | 200 | 14 | 234 | 88.973% | 92.212% | 6 | 1.440% |
| LAX | SON | 10 | 0 | 195 | 144 | 73.846% | 79.511% | 112 | 32 | 144 | 73.846% | 79.511% | 15 | 1.932% |
| LAX | SON | 10 | 1 | 256 | 97 | 37.891% | 43.971% | 102 | 15 | 176 | 68.750% | 74.115% | 19 | 1.478% |
| LAX | SON | 11 | 0 | 198 | 110 | 55.556% | 62.306% | 61 | 49 | 110 | 55.556% | 62.306% | 18 | 1.903% |
| LAX | SON | 11 | 1 | 253 | 40 | 15.810% | 20.813% | 51 | 13 | 132 | 52.174% | 58.251% | 33 | 1.496% |
| LAX | SON | 12 | 0 | 192 | 71 | 36.979% | 44.000% | 18 | 54 | 71 | 36.979% | 44.000% | 27 | 1.962% |
| LAX | SON | 12 | 1 | 259 | 23 | 8.880% | 12.972% | 20 | 11 | 98 | 37.838% | 43.881% | 50 | 1.462% |
| LAX | SON | 13 | 0 | 189 | 58 | 30.688% | 37.593% | 3 | 55 | 58 | 30.688% | 37.593% | 29 | 1.992% |
| LAX | SON | 13 | 1 | 262 | 16 | 6.107% | 9.689% | 9 | 11 | 84 | 32.061% | 37.937% | 56 | 1.445% |
| LAX | SON | 14 | 0 | 193 | 58 | 30.052% | 36.858% | 1 | 57 | 58 | 30.052% | 36.858% | 30 | 1.952% |
| LAX | SON | 14 | 1 | 258 | 12 | 4.651% | 7.953% | 2 | 10 | 74 | 28.682% | 34.482% | 60 | 1.467% |
| LAX | SON | 15 | 0 | 194 | 59 | 30.412% | 37.214% | 2 | 57 | 59 | 30.412% | 37.214% | 30 | 1.942% |
| LAX | SON | 15 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 16 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 16 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 17 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 17 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 18 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 18 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 19 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 19 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 20 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 20 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 21 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 21 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 22 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 22 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| LAX | SON | 23 | 0 | 194 | 57 | 29.381% | 36.142% | 0 | 57 | 57 | 29.381% | 36.142% | 30 | 1.942% |
| LAX | SON | 23 | 1 | 257 | 10 | 3.891% | 7.013% | 0 | 10 | 72 | 28.016% | 33.799% | 60 | 1.473% |
| MDW | DJF | 00 | 0 | 219 | 189 | 86.301% | 90.233% | 186 | 3 | 189 | 86.301% | 90.233% | 6 | 1.724% |
| MDW | DJF | 00 | 1 | 232 | 180 | 77.586% | 82.478% | 184 | 1 | 194 | 83.621% | 87.828% | 12 | 1.629% |
| MDW | DJF | 01 | 0 | 216 | 185 | 85.648% | 89.701% | 182 | 3 | 185 | 85.648% | 89.701% | 6 | 1.747% |
| MDW | DJF | 01 | 1 | 235 | 179 | 76.170% | 81.169% | 184 | 1 | 194 | 82.553% | 86.871% | 12 | 1.608% |
| MDW | DJF | 02 | 0 | 218 | 184 | 84.404% | 88.619% | 181 | 3 | 184 | 84.404% | 88.619% | 6 | 1.732% |
| MDW | DJF | 02 | 1 | 233 | 179 | 76.824% | 81.780% | 184 | 1 | 191 | 81.974% | 86.379% | 12 | 1.622% |
| MDW | DJF | 03 | 0 | 219 | 184 | 84.018% | 88.279% | 181 | 3 | 184 | 84.018% | 88.279% | 6 | 1.724% |
| MDW | DJF | 03 | 1 | 232 | 177 | 76.293% | 81.309% | 182 | 1 | 189 | 81.466% | 85.939% | 12 | 1.629% |
| MDW | DJF | 04 | 0 | 215 | 180 | 83.721% | 88.056% | 177 | 3 | 180 | 83.721% | 88.056% | 6 | 1.755% |
| MDW | DJF | 04 | 1 | 236 | 180 | 76.271% | 81.251% | 184 | 1 | 192 | 81.356% | 85.808% | 13 | 1.602% |
| MDW | DJF | 05 | 0 | 220 | 182 | 82.727% | 87.149% | 179 | 3 | 182 | 82.727% | 87.149% | 8 | 1.716% |
| MDW | DJF | 05 | 1 | 231 | 174 | 75.325% | 80.440% | 177 | 1 | 186 | 80.519% | 85.110% | 14 | 1.636% |
| MDW | DJF | 06 | 0 | 219 | 181 | 82.648% | 87.089% | 178 | 3 | 181 | 82.648% | 87.089% | 8 | 1.724% |
| MDW | DJF | 06 | 1 | 232 | 173 | 74.569% | 79.741% | 176 | 2 | 186 | 80.172% | 84.793% | 14 | 1.629% |
| MDW | DJF | 07 | 0 | 215 | 177 | 82.326% | 86.844% | 174 | 3 | 177 | 82.326% | 86.844% | 8 | 1.755% |
| MDW | DJF | 07 | 1 | 236 | 175 | 74.153% | 79.320% | 179 | 2 | 189 | 80.085% | 84.680% | 14 | 1.602% |
| MDW | DJF | 08 | 0 | 222 | 181 | 81.532% | 86.084% | 177 | 4 | 181 | 81.532% | 86.084% | 8 | 1.701% |
| MDW | DJF | 08 | 1 | 229 | 165 | 72.052% | 77.464% | 168 | 2 | 180 | 78.603% | 83.419% | 15 | 1.650% |
| MDW | DJF | 09 | 0 | 200 | 157 | 78.500% | 83.628% | 153 | 4 | 157 | 78.500% | 83.628% | 8 | 1.885% |
| MDW | DJF | 09 | 1 | 251 | 176 | 70.120% | 75.444% | 182 | 3 | 199 | 79.283% | 83.837% | 15 | 1.507% |
| MDW | DJF | 10 | 0 | 210 | 162 | 77.143% | 82.304% | 156 | 6 | 162 | 77.143% | 82.304% | 9 | 1.796% |
| MDW | DJF | 10 | 1 | 241 | 146 | 60.581% | 66.538% | 158 | 1 | 184 | 76.349% | 81.274% | 16 | 1.569% |
| MDW | DJF | 11 | 0 | 226 | 164 | 72.566% | 77.970% | 157 | 7 | 164 | 72.566% | 77.970% | 14 | 1.671% |
| MDW | DJF | 11 | 1 | 225 | 109 | 48.444% | 54.946% | 120 | 3 | 153 | 68.000% | 73.749% | 23 | 1.679% |
| MDW | DJF | 12 | 0 | 214 | 127 | 59.346% | 65.706% | 116 | 11 | 127 | 59.346% | 65.706% | 23 | 1.763% |
| MDW | DJF | 12 | 1 | 237 | 86 | 36.287% | 42.582% | 97 | 6 | 139 | 58.650% | 64.733% | 29 | 1.595% |
| MDW | DJF | 13 | 0 | 216 | 90 | 41.667% | 48.331% | 73 | 17 | 90 | 41.667% | 48.331% | 33 | 1.747% |
| MDW | DJF | 13 | 1 | 235 | 38 | 16.170% | 21.415% | 54 | 1 | 94 | 40.000% | 46.376% | 37 | 1.608% |
| MDW | DJF | 14 | 0 | 218 | 72 | 33.028% | 39.517% | 54 | 18 | 72 | 33.028% | 39.517% | 37 | 1.732% |
| MDW | DJF | 14 | 1 | 233 | 17 | 7.296% | 11.373% | 30 | 0 | 60 | 25.751% | 31.727% | 44 | 1.622% |
| MDW | DJF | 15 | 0 | 214 | 55 | 25.701% | 31.948% | 37 | 18 | 55 | 25.701% | 31.948% | 42 | 1.763% |
| MDW | DJF | 15 | 1 | 237 | 16 | 6.751% | 10.684% | 21 | 0 | 49 | 20.675% | 26.279% | 52 | 1.595% |
| MDW | DJF | 16 | 0 | 212 | 51 | 24.057% | 30.239% | 33 | 18 | 51 | 24.057% | 30.239% | 43 | 1.780% |
| MDW | DJF | 16 | 1 | 239 | 14 | 5.858% | 9.591% | 16 | 0 | 44 | 18.410% | 23.810% | 55 | 1.582% |
| MDW | DJF | 17 | 0 | 212 | 47 | 22.170% | 28.229% | 29 | 18 | 47 | 22.170% | 28.229% | 44 | 1.780% |
| MDW | DJF | 17 | 1 | 239 | 12 | 5.021% | 8.570% | 14 | 0 | 41 | 17.155% | 22.444% | 55 | 1.582% |
| MDW | DJF | 18 | 0 | 209 | 42 | 20.096% | 26.046% | 24 | 18 | 42 | 20.096% | 26.046% | 45 | 1.805% |
| MDW | DJF | 18 | 1 | 242 | 14 | 5.785% | 9.475% | 16 | 0 | 43 | 17.769% | 23.077% | 55 | 1.563% |
| MDW | DJF | 19 | 0 | 210 | 40 | 19.048% | 24.896% | 22 | 18 | 40 | 19.048% | 24.896% | 46 | 1.796% |
| MDW | DJF | 19 | 1 | 241 | 10 | 4.149% | 7.468% | 13 | 0 | 39 | 16.183% | 21.357% | 55 | 1.569% |
| MDW | DJF | 20 | 0 | 209 | 36 | 17.225% | 22.924% | 18 | 18 | 36 | 17.225% | 22.924% | 48 | 1.805% |
| MDW | DJF | 20 | 1 | 242 | 9 | 3.719% | 6.916% | 10 | 0 | 35 | 14.463% | 19.450% | 57 | 1.563% |
| MDW | DJF | 21 | 0 | 209 | 34 | 16.268% | 21.872% | 16 | 18 | 34 | 16.268% | 21.872% | 49 | 1.805% |
| MDW | DJF | 21 | 1 | 242 | 4 | 1.653% | 4.172% | 6 | 0 | 32 | 13.223% | 18.071% | 57 | 1.563% |
| MDW | DJF | 22 | 0 | 209 | 28 | 13.397% | 18.681% | 10 | 18 | 28 | 13.397% | 18.681% | 49 | 1.805% |
| MDW | DJF | 22 | 1 | 242 | 1 | 0.413% | 2.303% | 3 | 0 | 30 | 12.397% | 17.145% | 58 | 1.563% |
| MDW | DJF | 23 | 0 | 204 | 18 | 8.824% | 13.515% | 0 | 18 | 18 | 8.824% | 13.515% | 52 | 1.848% |
| MDW | DJF | 23 | 1 | 247 | 0 | 0.000% | 1.531% | 0 | 0 | 25 | 10.121% | 14.514% | 60 | 1.531% |
| MDW | JJA | 00 | 0 | 239 | 232 | 97.071% | 98.574% | 232 | 0 | 232 | 97.071% | 98.574% | 0 | 1.582% |
| MDW | JJA | 00 | 1 | 220 | 212 | 96.364% | 98.146% | 211 | 1 | 215 | 97.727% | 99.025% | 2 | 1.716% |
| MDW | JJA | 01 | 0 | 235 | 228 | 97.021% | 98.550% | 228 | 0 | 228 | 97.021% | 98.550% | 0 | 1.608% |
| MDW | JJA | 01 | 1 | 224 | 216 | 96.429% | 98.179% | 215 | 1 | 219 | 97.768% | 99.043% | 2 | 1.686% |
| MDW | JJA | 02 | 0 | 239 | 232 | 97.071% | 98.574% | 232 | 0 | 232 | 97.071% | 98.574% | 0 | 1.582% |
| MDW | JJA | 02 | 1 | 220 | 212 | 96.364% | 98.146% | 211 | 1 | 215 | 97.727% | 99.025% | 2 | 1.716% |
| MDW | JJA | 03 | 0 | 245 | 238 | 97.143% | 98.609% | 238 | 0 | 238 | 97.143% | 98.609% | 0 | 1.544% |
| MDW | JJA | 03 | 1 | 214 | 206 | 96.262% | 98.094% | 205 | 1 | 209 | 97.664% | 98.998% | 2 | 1.763% |
| MDW | JJA | 04 | 0 | 242 | 235 | 97.107% | 98.592% | 235 | 0 | 235 | 97.107% | 98.592% | 0 | 1.563% |
| MDW | JJA | 04 | 1 | 217 | 209 | 96.313% | 98.120% | 208 | 1 | 212 | 97.696% | 99.012% | 2 | 1.739% |
| MDW | JJA | 05 | 0 | 241 | 234 | 97.095% | 98.586% | 234 | 0 | 234 | 97.095% | 98.586% | 0 | 1.569% |
| MDW | JJA | 05 | 1 | 218 | 209 | 95.872% | 97.813% | 207 | 2 | 212 | 97.248% | 98.733% | 2 | 1.732% |
| MDW | JJA | 06 | 0 | 249 | 241 | 96.787% | 98.363% | 240 | 1 | 241 | 96.787% | 98.363% | 0 | 1.519% |
| MDW | JJA | 06 | 1 | 210 | 201 | 95.714% | 97.729% | 200 | 1 | 204 | 97.143% | 98.684% | 2 | 1.796% |
| MDW | JJA | 07 | 0 | 247 | 237 | 95.951% | 97.786% | 236 | 1 | 237 | 95.951% | 97.786% | 0 | 1.531% |
| MDW | JJA | 07 | 1 | 212 | 204 | 96.226% | 98.076% | 203 | 1 | 206 | 97.170% | 98.697% | 2 | 1.780% |
| MDW | JJA | 08 | 0 | 260 | 247 | 95.000% | 97.055% | 246 | 1 | 247 | 95.000% | 97.055% | 1 | 1.456% |
| MDW | JJA | 08 | 1 | 199 | 188 | 94.472% | 96.886% | 187 | 1 | 191 | 95.980% | 97.949% | 2 | 1.894% |
| MDW | JJA | 09 | 0 | 241 | 226 | 93.776% | 96.192% | 222 | 4 | 226 | 93.776% | 96.192% | 2 | 1.569% |
| MDW | JJA | 09 | 1 | 218 | 194 | 88.991% | 92.489% | 193 | 4 | 205 | 94.037% | 96.482% | 3 | 1.732% |
| MDW | JJA | 10 | 0 | 236 | 209 | 88.559% | 92.017% | 201 | 8 | 209 | 88.559% | 92.017% | 5 | 1.602% |
| MDW | JJA | 10 | 1 | 223 | 179 | 80.269% | 84.961% | 176 | 8 | 202 | 90.583% | 93.758% | 5 | 1.693% |
| MDW | JJA | 11 | 0 | 223 | 176 | 78.924% | 83.764% | 158 | 18 | 176 | 78.924% | 83.764% | 10 | 1.693% |
| MDW | JJA | 11 | 1 | 236 | 138 | 58.475% | 64.577% | 138 | 12 | 196 | 83.051% | 87.299% | 8 | 1.602% |
| MDW | JJA | 12 | 0 | 224 | 142 | 63.393% | 69.426% | 111 | 31 | 142 | 63.393% | 69.426% | 15 | 1.686% |
| MDW | JJA | 12 | 1 | 235 | 80 | 34.043% | 40.314% | 85 | 9 | 160 | 68.085% | 73.713% | 14 | 1.608% |
| MDW | JJA | 13 | 0 | 224 | 99 | 44.196% | 50.743% | 59 | 40 | 99 | 44.196% | 50.743% | 26 | 1.686% |
| MDW | JJA | 13 | 1 | 235 | 33 | 14.043% | 19.065% | 43 | 2 | 111 | 47.234% | 53.610% | 23 | 1.608% |
| MDW | JJA | 14 | 0 | 224 | 62 | 27.679% | 33.877% | 20 | 42 | 62 | 27.679% | 33.877% | 34 | 1.686% |
| MDW | JJA | 14 | 1 | 235 | 9 | 3.830% | 7.117% | 13 | 1 | 70 | 29.787% | 35.921% | 34 | 1.608% |
| MDW | JJA | 15 | 0 | 223 | 48 | 21.525% | 27.377% | 6 | 42 | 48 | 21.525% | 27.377% | 37 | 1.693% |
| MDW | JJA | 15 | 1 | 236 | 4 | 1.695% | 4.276% | 3 | 2 | 55 | 23.305% | 29.100% | 38 | 1.602% |
| MDW | JJA | 16 | 0 | 223 | 43 | 19.283% | 24.963% | 1 | 42 | 43 | 19.283% | 24.963% | 38 | 1.693% |
| MDW | JJA | 16 | 1 | 236 | 2 | 0.847% | 3.037% | 0 | 2 | 50 | 21.186% | 26.840% | 39 | 1.602% |
| MDW | JJA | 17 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 17 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 18 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 18 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 19 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 19 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 20 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 20 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 21 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 21 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 22 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 22 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | JJA | 23 | 0 | 224 | 43 | 19.196% | 24.856% | 0 | 43 | 43 | 19.196% | 24.856% | 38 | 1.686% |
| MDW | JJA | 23 | 1 | 235 | 1 | 0.426% | 2.371% | 0 | 1 | 48 | 20.426% | 26.036% | 39 | 1.608% |
| MDW | MAM | 00 | 0 | 236 | 216 | 91.525% | 94.447% | 209 | 7 | 216 | 91.525% | 94.447% | 6 | 1.602% |
| MDW | MAM | 00 | 1 | 224 | 200 | 89.286% | 92.694% | 199 | 2 | 206 | 91.964% | 94.857% | 2 | 1.686% |
| MDW | MAM | 01 | 0 | 236 | 216 | 91.525% | 94.447% | 209 | 7 | 216 | 91.525% | 94.447% | 6 | 1.602% |
| MDW | MAM | 01 | 1 | 224 | 198 | 88.393% | 91.955% | 197 | 2 | 204 | 91.071% | 94.146% | 2 | 1.686% |
| MDW | MAM | 02 | 0 | 239 | 218 | 91.213% | 94.181% | 211 | 7 | 218 | 91.213% | 94.181% | 6 | 1.582% |
| MDW | MAM | 02 | 1 | 221 | 196 | 88.688% | 92.219% | 195 | 2 | 201 | 90.950% | 94.065% | 2 | 1.709% |
| MDW | MAM | 03 | 0 | 237 | 216 | 91.139% | 94.132% | 209 | 7 | 216 | 91.139% | 94.132% | 6 | 1.595% |
| MDW | MAM | 03 | 1 | 223 | 197 | 88.341% | 91.918% | 196 | 2 | 202 | 90.583% | 93.758% | 2 | 1.693% |
| MDW | MAM | 04 | 0 | 237 | 216 | 91.139% | 94.132% | 209 | 7 | 216 | 91.139% | 94.132% | 6 | 1.595% |
| MDW | MAM | 04 | 1 | 223 | 197 | 88.341% | 91.918% | 196 | 2 | 202 | 90.583% | 93.758% | 2 | 1.693% |
| MDW | MAM | 05 | 0 | 238 | 217 | 91.176% | 94.157% | 210 | 7 | 217 | 91.176% | 94.157% | 6 | 1.588% |
| MDW | MAM | 05 | 1 | 222 | 196 | 88.288% | 91.881% | 195 | 2 | 201 | 90.541% | 93.730% | 2 | 1.701% |
| MDW | MAM | 06 | 0 | 244 | 222 | 90.984% | 93.970% | 215 | 7 | 222 | 90.984% | 93.970% | 6 | 1.550% |
| MDW | MAM | 06 | 1 | 216 | 188 | 87.037% | 90.877% | 187 | 2 | 193 | 89.352% | 92.799% | 2 | 1.747% |
| MDW | MAM | 07 | 0 | 224 | 201 | 89.732% | 93.060% | 194 | 7 | 201 | 89.732% | 93.060% | 6 | 1.686% |
| MDW | MAM | 07 | 1 | 236 | 204 | 86.441% | 90.229% | 202 | 3 | 212 | 89.831% | 93.071% | 2 | 1.602% |
| MDW | MAM | 08 | 0 | 241 | 216 | 89.627% | 92.874% | 207 | 9 | 216 | 89.627% | 92.874% | 6 | 1.569% |
| MDW | MAM | 08 | 1 | 219 | 186 | 84.932% | 89.065% | 185 | 3 | 195 | 89.041% | 92.524% | 2 | 1.724% |
| MDW | MAM | 09 | 0 | 250 | 216 | 86.400% | 90.102% | 205 | 11 | 216 | 86.400% | 90.102% | 9 | 1.513% |
| MDW | MAM | 09 | 1 | 210 | 159 | 75.714% | 81.018% | 158 | 5 | 178 | 84.762% | 88.995% | 2 | 1.796% |
| MDW | MAM | 10 | 0 | 246 | 202 | 82.114% | 86.398% | 187 | 15 | 202 | 82.114% | 86.398% | 11 | 1.538% |
| MDW | MAM | 10 | 1 | 214 | 150 | 70.093% | 75.829% | 150 | 6 | 175 | 81.776% | 86.372% | 3 | 1.763% |
| MDW | MAM | 11 | 0 | 230 | 165 | 71.739% | 77.164% | 148 | 17 | 165 | 71.739% | 77.164% | 14 | 1.643% |
| MDW | MAM | 11 | 1 | 230 | 148 | 64.348% | 70.256% | 144 | 12 | 180 | 78.261% | 83.104% | 6 | 1.643% |
| MDW | MAM | 12 | 0 | 230 | 139 | 60.435% | 66.533% | 119 | 20 | 139 | 60.435% | 66.533% | 20 | 1.643% |
| MDW | MAM | 12 | 1 | 230 | 104 | 45.217% | 51.676% | 106 | 11 | 149 | 64.783% | 70.667% | 11 | 1.643% |
| MDW | MAM | 13 | 0 | 239 | 125 | 52.301% | 58.547% | 94 | 31 | 125 | 52.301% | 58.547% | 25 | 1.582% |
| MDW | MAM | 13 | 1 | 221 | 44 | 19.910% | 25.668% | 51 | 5 | 95 | 42.986% | 49.578% | 24 | 1.709% |
| MDW | MAM | 14 | 0 | 222 | 77 | 34.685% | 41.158% | 44 | 33 | 77 | 34.685% | 41.158% | 38 | 1.701% |
| MDW | MAM | 14 | 1 | 238 | 18 | 7.563% | 11.637% | 18 | 9 | 76 | 31.933% | 38.103% | 34 | 1.588% |
| MDW | MAM | 15 | 0 | 229 | 57 | 24.891% | 30.874% | 17 | 40 | 57 | 24.891% | 30.874% | 47 | 1.650% |
| MDW | MAM | 15 | 1 | 231 | 8 | 3.463% | 6.684% | 7 | 3 | 50 | 21.645% | 27.396% | 41 | 1.636% |
| MDW | MAM | 16 | 0 | 230 | 50 | 21.739% | 27.510% | 9 | 41 | 50 | 21.739% | 27.510% | 49 | 1.643% |
| MDW | MAM | 16 | 1 | 230 | 7 | 3.043% | 6.148% | 4 | 3 | 42 | 18.261% | 23.761% | 43 | 1.643% |
| MDW | MAM | 17 | 0 | 232 | 51 | 21.983% | 27.744% | 8 | 43 | 51 | 21.983% | 27.744% | 49 | 1.629% |
| MDW | MAM | 17 | 1 | 228 | 4 | 1.754% | 4.423% | 2 | 2 | 40 | 17.544% | 23.007% | 43 | 1.657% |
| MDW | MAM | 18 | 0 | 230 | 48 | 20.870% | 26.579% | 5 | 43 | 48 | 20.870% | 26.579% | 49 | 1.643% |
| MDW | MAM | 18 | 1 | 230 | 4 | 1.739% | 4.386% | 2 | 2 | 39 | 16.957% | 22.339% | 43 | 1.643% |
| MDW | MAM | 19 | 0 | 229 | 47 | 20.524% | 26.221% | 4 | 43 | 47 | 20.524% | 26.221% | 49 | 1.650% |
| MDW | MAM | 19 | 1 | 231 | 5 | 2.165% | 4.966% | 3 | 2 | 40 | 17.316% | 22.720% | 43 | 1.636% |
| MDW | MAM | 20 | 0 | 228 | 45 | 19.737% | 25.386% | 2 | 43 | 45 | 19.737% | 25.386% | 50 | 1.657% |
| MDW | MAM | 20 | 1 | 232 | 5 | 2.155% | 4.945% | 2 | 3 | 41 | 17.672% | 23.095% | 43 | 1.629% |
| MDW | MAM | 21 | 0 | 230 | 45 | 19.565% | 25.174% | 2 | 43 | 45 | 19.565% | 25.174% | 50 | 1.643% |
| MDW | MAM | 21 | 1 | 230 | 4 | 1.739% | 4.386% | 1 | 3 | 39 | 16.957% | 22.339% | 43 | 1.643% |
| MDW | MAM | 22 | 0 | 229 | 44 | 19.214% | 24.808% | 1 | 43 | 44 | 19.214% | 24.808% | 50 | 1.650% |
| MDW | MAM | 22 | 1 | 231 | 3 | 1.299% | 3.748% | 0 | 3 | 38 | 16.450% | 21.772% | 43 | 1.636% |
| MDW | MAM | 23 | 0 | 229 | 44 | 19.214% | 24.808% | 0 | 44 | 44 | 19.214% | 24.808% | 50 | 1.650% |
| MDW | MAM | 23 | 1 | 231 | 2 | 0.866% | 3.101% | 0 | 2 | 37 | 16.017% | 21.297% | 43 | 1.636% |
| MDW | SON | 00 | 0 | 208 | 189 | 90.865% | 94.074% | 189 | 0 | 189 | 90.865% | 94.074% | 3 | 1.813% |
| MDW | SON | 00 | 1 | 247 | 218 | 88.259% | 91.700% | 219 | 3 | 228 | 92.308% | 95.020% | 7 | 1.531% |
| MDW | SON | 01 | 0 | 209 | 190 | 90.909% | 94.103% | 190 | 0 | 190 | 90.909% | 94.103% | 3 | 1.805% |
| MDW | SON | 01 | 1 | 246 | 216 | 87.805% | 91.323% | 216 | 3 | 225 | 91.463% | 94.349% | 8 | 1.538% |
| MDW | SON | 02 | 0 | 206 | 187 | 90.777% | 94.016% | 187 | 0 | 187 | 90.777% | 94.016% | 3 | 1.831% |
| MDW | SON | 02 | 1 | 249 | 218 | 87.550% | 91.089% | 218 | 3 | 227 | 91.165% | 94.093% | 8 | 1.519% |
| MDW | SON | 03 | 0 | 202 | 183 | 90.594% | 93.896% | 183 | 0 | 183 | 90.594% | 93.896% | 3 | 1.866% |
| MDW | SON | 03 | 1 | 253 | 221 | 87.352% | 90.896% | 221 | 3 | 231 | 91.304% | 94.187% | 8 | 1.496% |
| MDW | SON | 04 | 0 | 194 | 175 | 90.206% | 93.640% | 175 | 0 | 175 | 90.206% | 93.640% | 3 | 1.942% |
| MDW | SON | 04 | 1 | 261 | 229 | 87.739% | 91.180% | 229 | 3 | 239 | 91.571% | 94.368% | 8 | 1.450% |
| MDW | SON | 05 | 0 | 196 | 176 | 89.796% | 93.297% | 176 | 0 | 176 | 89.796% | 93.297% | 4 | 1.922% |
| MDW | SON | 05 | 1 | 259 | 227 | 87.645% | 91.111% | 226 | 4 | 237 | 91.506% | 94.324% | 8 | 1.462% |
| MDW | SON | 06 | 0 | 194 | 174 | 89.691% | 93.227% | 173 | 1 | 174 | 89.691% | 93.227% | 4 | 1.942% |
| MDW | SON | 06 | 1 | 261 | 226 | 86.590% | 90.197% | 226 | 3 | 238 | 91.188% | 94.056% | 9 | 1.450% |
| MDW | SON | 07 | 0 | 211 | 189 | 89.573% | 93.013% | 189 | 1 | 189 | 89.573% | 93.013% | 5 | 1.788% |
| MDW | SON | 07 | 1 | 244 | 209 | 85.656% | 89.502% | 209 | 3 | 220 | 90.164% | 93.301% | 9 | 1.550% |
| MDW | SON | 08 | 0 | 220 | 198 | 90.000% | 93.303% | 197 | 1 | 198 | 90.000% | 93.303% | 4 | 1.716% |
| MDW | SON | 08 | 1 | 235 | 198 | 84.255% | 88.356% | 197 | 4 | 210 | 89.362% | 92.690% | 10 | 1.608% |
| MDW | SON | 09 | 0 | 228 | 204 | 89.474% | 92.824% | 203 | 1 | 204 | 89.474% | 92.824% | 4 | 1.657% |
| MDW | SON | 09 | 1 | 227 | 180 | 79.295% | 84.057% | 178 | 7 | 198 | 87.225% | 90.956% | 11 | 1.664% |
| MDW | SON | 10 | 0 | 226 | 194 | 85.841% | 89.788% | 188 | 6 | 194 | 85.841% | 89.788% | 4 | 1.671% |
| MDW | SON | 10 | 1 | 229 | 156 | 68.122% | 73.816% | 161 | 6 | 189 | 82.533% | 86.902% | 12 | 1.650% |
| MDW | SON | 11 | 0 | 210 | 156 | 74.286% | 79.724% | 146 | 10 | 156 | 74.286% | 79.724% | 8 | 1.796% |
| MDW | SON | 11 | 1 | 245 | 126 | 51.429% | 57.616% | 136 | 5 | 179 | 73.061% | 78.229% | 18 | 1.544% |
| MDW | SON | 12 | 0 | 195 | 119 | 61.026% | 67.595% | 105 | 14 | 119 | 61.026% | 67.595% | 10 | 1.932% |
| MDW | SON | 12 | 1 | 260 | 61 | 23.462% | 28.976% | 75 | 3 | 150 | 57.692% | 63.543% | 32 | 1.456% |
| MDW | SON | 13 | 0 | 194 | 72 | 37.113% | 44.100% | 52 | 21 | 72 | 37.113% | 44.100% | 20 | 1.942% |
| MDW | SON | 13 | 1 | 261 | 20 | 7.663% | 11.539% | 30 | 2 | 102 | 39.080% | 45.117% | 41 | 1.450% |
| MDW | SON | 14 | 0 | 193 | 42 | 21.762% | 28.103% | 20 | 22 | 42 | 21.762% | 28.103% | 27 | 1.952% |
| MDW | SON | 14 | 1 | 262 | 9 | 3.435% | 6.398% | 11 | 1 | 67 | 25.573% | 31.182% | 52 | 1.445% |
| MDW | SON | 15 | 0 | 191 | 29 | 15.183% | 20.955% | 7 | 22 | 29 | 15.183% | 20.955% | 29 | 1.972% |
| MDW | SON | 15 | 1 | 264 | 8 | 3.030% | 5.865% | 8 | 1 | 57 | 21.591% | 26.943% | 54 | 1.434% |
| MDW | SON | 16 | 0 | 190 | 28 | 14.737% | 20.474% | 6 | 22 | 28 | 14.737% | 20.474% | 29 | 1.982% |
| MDW | SON | 16 | 1 | 265 | 6 | 2.264% | 4.851% | 6 | 1 | 55 | 20.755% | 26.038% | 54 | 1.429% |
| MDW | SON | 17 | 0 | 188 | 25 | 13.298% | 18.894% | 3 | 22 | 25 | 13.298% | 18.894% | 29 | 2.002% |
| MDW | SON | 17 | 1 | 267 | 3 | 1.124% | 3.251% | 2 | 1 | 51 | 19.101% | 24.241% | 55 | 1.418% |
| MDW | SON | 18 | 0 | 186 | 23 | 12.366% | 17.871% | 1 | 22 | 23 | 12.366% | 17.871% | 29 | 2.024% |
| MDW | SON | 18 | 1 | 269 | 4 | 1.487% | 3.760% | 3 | 1 | 53 | 19.703% | 24.868% | 55 | 1.408% |
| MDW | SON | 19 | 0 | 186 | 23 | 12.366% | 17.871% | 1 | 22 | 23 | 12.366% | 17.871% | 29 | 2.024% |
| MDW | SON | 19 | 1 | 269 | 4 | 1.487% | 3.760% | 3 | 1 | 53 | 19.703% | 24.868% | 55 | 1.408% |
| MDW | SON | 20 | 0 | 187 | 23 | 12.299% | 17.779% | 1 | 22 | 23 | 12.299% | 17.779% | 29 | 2.013% |
| MDW | SON | 20 | 1 | 268 | 4 | 1.493% | 3.774% | 3 | 1 | 52 | 19.403% | 24.556% | 55 | 1.413% |
| MDW | SON | 21 | 0 | 187 | 23 | 12.299% | 17.779% | 1 | 22 | 23 | 12.299% | 17.779% | 29 | 2.013% |
| MDW | SON | 21 | 1 | 268 | 3 | 1.119% | 3.239% | 2 | 1 | 51 | 19.030% | 24.154% | 55 | 1.413% |
| MDW | SON | 22 | 0 | 190 | 23 | 12.105% | 17.509% | 1 | 22 | 23 | 12.105% | 17.509% | 30 | 1.982% |
| MDW | SON | 22 | 1 | 265 | 1 | 0.377% | 2.106% | 0 | 1 | 48 | 18.113% | 23.195% | 55 | 1.429% |
| MDW | SON | 23 | 0 | 190 | 22 | 11.579% | 16.909% | 0 | 22 | 22 | 11.579% | 16.909% | 30 | 1.982% |
| MDW | SON | 23 | 1 | 265 | 1 | 0.377% | 2.106% | 0 | 1 | 47 | 17.736% | 22.786% | 55 | 1.429% |
| MIA | DJF | 00 | 0 | 226 | 222 | 98.230% | 99.310% | 219 | 3 | 222 | 98.230% | 99.310% | 0 | 1.671% |
| MIA | DJF | 00 | 1 | 224 | 215 | 95.982% | 97.872% | 216 | 1 | 219 | 97.768% | 99.043% | 2 | 1.686% |
| MIA | DJF | 01 | 0 | 222 | 218 | 98.198% | 99.297% | 215 | 3 | 218 | 98.198% | 99.297% | 0 | 1.701% |
| MIA | DJF | 01 | 1 | 228 | 219 | 96.053% | 97.910% | 220 | 1 | 223 | 97.807% | 99.060% | 2 | 1.657% |
| MIA | DJF | 02 | 0 | 221 | 217 | 98.190% | 99.294% | 214 | 3 | 217 | 98.190% | 99.294% | 0 | 1.709% |
| MIA | DJF | 02 | 1 | 229 | 219 | 95.633% | 97.611% | 219 | 2 | 223 | 97.380% | 98.794% | 3 | 1.650% |
| MIA | DJF | 03 | 0 | 224 | 220 | 98.214% | 99.303% | 217 | 3 | 220 | 98.214% | 99.303% | 0 | 1.686% |
| MIA | DJF | 03 | 1 | 226 | 216 | 95.575% | 97.579% | 216 | 2 | 220 | 97.345% | 98.778% | 3 | 1.671% |
| MIA | DJF | 04 | 0 | 221 | 217 | 98.190% | 99.294% | 214 | 3 | 217 | 98.190% | 99.294% | 0 | 1.709% |
| MIA | DJF | 04 | 1 | 229 | 218 | 95.197% | 97.297% | 218 | 2 | 223 | 97.380% | 98.794% | 3 | 1.650% |
| MIA | DJF | 05 | 0 | 220 | 216 | 98.182% | 99.291% | 213 | 3 | 216 | 98.182% | 99.291% | 0 | 1.716% |
| MIA | DJF | 05 | 1 | 230 | 219 | 95.217% | 97.309% | 219 | 2 | 224 | 97.391% | 98.799% | 3 | 1.643% |
| MIA | DJF | 06 | 0 | 218 | 214 | 98.165% | 99.284% | 211 | 3 | 214 | 98.165% | 99.284% | 0 | 1.732% |
| MIA | DJF | 06 | 1 | 232 | 221 | 95.259% | 97.332% | 221 | 2 | 226 | 97.414% | 98.809% | 3 | 1.629% |
| MIA | DJF | 07 | 0 | 218 | 214 | 98.165% | 99.284% | 211 | 3 | 214 | 98.165% | 99.284% | 0 | 1.732% |
| MIA | DJF | 07 | 1 | 232 | 220 | 94.828% | 97.017% | 220 | 2 | 226 | 97.414% | 98.809% | 3 | 1.629% |
| MIA | DJF | 08 | 0 | 262 | 256 | 97.710% | 98.946% | 253 | 3 | 256 | 97.710% | 98.946% | 0 | 1.445% |
| MIA | DJF | 08 | 1 | 188 | 176 | 93.617% | 96.311% | 177 | 2 | 182 | 96.809% | 98.529% | 3 | 2.002% |
| MIA | DJF | 09 | 0 | 297 | 286 | 96.296% | 97.920% | 283 | 3 | 286 | 96.296% | 97.920% | 1 | 1.277% |
| MIA | DJF | 09 | 1 | 153 | 138 | 90.196% | 93.968% | 137 | 3 | 144 | 94.118% | 96.875% | 4 | 2.449% |
| MIA | DJF | 10 | 0 | 280 | 242 | 86.429% | 89.950% | 232 | 10 | 242 | 86.429% | 89.950% | 4 | 1.353% |
| MIA | DJF | 10 | 1 | 170 | 133 | 78.235% | 83.777% | 131 | 4 | 154 | 90.588% | 94.124% | 4 | 2.210% |
| MIA | DJF | 11 | 0 | 275 | 197 | 71.636% | 76.637% | 178 | 19 | 197 | 71.636% | 76.637% | 11 | 1.378% |
| MIA | DJF | 11 | 1 | 175 | 90 | 51.429% | 58.723% | 84 | 10 | 135 | 77.143% | 82.742% | 4 | 2.148% |
| MIA | DJF | 12 | 0 | 242 | 124 | 51.240% | 57.469% | 101 | 23 | 124 | 51.240% | 57.469% | 22 | 1.563% |
| MIA | DJF | 12 | 1 | 208 | 50 | 24.038% | 30.283% | 43 | 14 | 124 | 59.615% | 66.051% | 5 | 1.813% |
| MIA | DJF | 13 | 0 | 225 | 69 | 30.667% | 36.974% | 36 | 33 | 69 | 30.667% | 36.974% | 39 | 1.679% |
| MIA | DJF | 13 | 1 | 225 | 24 | 10.667% | 15.381% | 18 | 7 | 102 | 45.333% | 51.862% | 12 | 1.679% |
| MIA | DJF | 14 | 0 | 232 | 50 | 21.552% | 27.283% | 15 | 35 | 50 | 21.552% | 27.283% | 44 | 1.629% |
| MIA | DJF | 14 | 1 | 218 | 11 | 5.046% | 8.808% | 6 | 5 | 76 | 34.862% | 41.401% | 13 | 1.732% |
| MIA | DJF | 15 | 0 | 229 | 36 | 15.721% | 20.995% | 0 | 36 | 36 | 15.721% | 20.995% | 48 | 1.650% |
| MIA | DJF | 15 | 1 | 221 | 7 | 3.167% | 6.393% | 3 | 4 | 72 | 32.579% | 39.010% | 14 | 1.709% |
| MIA | DJF | 16 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 16 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 17 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 17 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 18 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 18 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 19 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 19 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 20 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 20 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 21 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 21 | 1 | 220 | 6 | 2.727% | 5.821% | 2 | 4 | 70 | 31.818% | 38.240% | 14 | 1.716% |
| MIA | DJF | 22 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 22 | 1 | 220 | 4 | 1.818% | 4.581% | 0 | 4 | 68 | 30.909% | 37.299% | 14 | 1.716% |
| MIA | DJF | 23 | 0 | 230 | 36 | 15.652% | 20.908% | 0 | 36 | 36 | 15.652% | 20.908% | 48 | 1.643% |
| MIA | DJF | 23 | 1 | 220 | 4 | 1.818% | 4.581% | 0 | 4 | 68 | 30.909% | 37.299% | 14 | 1.716% |
| MIA | JJA | 00 | 0 | 211 | 211 | 100.000% | 100.000% | 211 | 0 | 211 | 100.000% | 100.000% | 0 | 1.788% |
| MIA | JJA | 00 | 1 | 239 | 236 | 98.745% | 99.572% | 236 | 0 | 238 | 99.582% | 99.926% | 0 | 1.582% |
| MIA | JJA | 01 | 0 | 210 | 210 | 100.000% | 100.000% | 210 | 0 | 210 | 100.000% | 100.000% | 0 | 1.796% |
| MIA | JJA | 01 | 1 | 240 | 237 | 98.750% | 99.574% | 237 | 0 | 239 | 99.583% | 99.926% | 0 | 1.575% |
| MIA | JJA | 02 | 0 | 208 | 208 | 100.000% | 100.000% | 208 | 0 | 208 | 100.000% | 100.000% | 0 | 1.813% |
| MIA | JJA | 02 | 1 | 242 | 239 | 98.760% | 99.578% | 239 | 0 | 241 | 99.587% | 99.927% | 0 | 1.563% |
| MIA | JJA | 03 | 0 | 208 | 208 | 100.000% | 100.000% | 208 | 0 | 208 | 100.000% | 100.000% | 0 | 1.813% |
| MIA | JJA | 03 | 1 | 242 | 239 | 98.760% | 99.578% | 239 | 0 | 241 | 99.587% | 99.927% | 0 | 1.563% |
| MIA | JJA | 04 | 0 | 207 | 207 | 100.000% | 100.000% | 207 | 0 | 207 | 100.000% | 100.000% | 0 | 1.822% |
| MIA | JJA | 04 | 1 | 243 | 240 | 98.765% | 99.579% | 240 | 0 | 242 | 99.588% | 99.927% | 0 | 1.556% |
| MIA | JJA | 05 | 0 | 206 | 206 | 100.000% | 100.000% | 206 | 0 | 206 | 100.000% | 100.000% | 0 | 1.831% |
| MIA | JJA | 05 | 1 | 244 | 241 | 98.770% | 99.581% | 241 | 0 | 243 | 99.590% | 99.928% | 0 | 1.550% |
| MIA | JJA | 06 | 0 | 214 | 214 | 100.000% | 100.000% | 214 | 0 | 214 | 100.000% | 100.000% | 0 | 1.763% |
| MIA | JJA | 06 | 1 | 236 | 233 | 98.729% | 99.567% | 233 | 0 | 235 | 99.576% | 99.925% | 0 | 1.602% |
| MIA | JJA | 07 | 0 | 149 | 149 | 100.000% | 100.000% | 149 | 0 | 149 | 100.000% | 100.000% | 0 | 2.513% |
| MIA | JJA | 07 | 1 | 301 | 298 | 99.003% | 99.660% | 298 | 0 | 300 | 99.668% | 99.941% | 0 | 1.260% |
| MIA | JJA | 08 | 0 | 71 | 70 | 98.592% | 99.751% | 70 | 0 | 70 | 98.592% | 99.751% | 0 | 5.133% |
| MIA | JJA | 08 | 1 | 379 | 358 | 94.459% | 96.348% | 358 | 7 | 369 | 97.361% | 98.561% | 1 | 1.003% |
| MIA | JJA | 09 | 0 | 83 | 82 | 98.795% | 99.787% | 80 | 2 | 82 | 98.795% | 99.787% | 0 | 4.424% |
| MIA | JJA | 09 | 1 | 367 | 288 | 78.474% | 82.373% | 273 | 32 | 336 | 91.553% | 93.986% | 6 | 1.036% |
| MIA | JJA | 10 | 0 | 143 | 128 | 89.510% | 93.540% | 96 | 32 | 128 | 89.510% | 93.540% | 0 | 2.616% |
| MIA | JJA | 10 | 1 | 307 | 136 | 44.300% | 49.893% | 124 | 32 | 225 | 73.290% | 77.929% | 18 | 1.236% |
| MIA | JJA | 11 | 0 | 182 | 131 | 71.978% | 77.997% | 69 | 62 | 131 | 71.978% | 77.997% | 1 | 2.067% |
| MIA | JJA | 11 | 1 | 268 | 56 | 20.896% | 26.157% | 54 | 17 | 145 | 54.104% | 59.970% | 24 | 1.413% |
| MIA | JJA | 12 | 0 | 203 | 108 | 53.202% | 59.943% | 31 | 77 | 108 | 53.202% | 59.943% | 4 | 1.857% |
| MIA | JJA | 12 | 1 | 247 | 26 | 10.526% | 14.976% | 34 | 7 | 101 | 40.891% | 47.116% | 28 | 1.531% |
| MIA | JJA | 13 | 0 | 225 | 99 | 44.000% | 50.533% | 14 | 85 | 99 | 44.000% | 50.533% | 6 | 1.679% |
| MIA | JJA | 13 | 1 | 225 | 8 | 3.556% | 6.858% | 14 | 0 | 53 | 23.556% | 29.515% | 37 | 1.679% |
| MIA | JJA | 14 | 0 | 225 | 89 | 39.556% | 46.069% | 4 | 85 | 89 | 39.556% | 46.069% | 8 | 1.679% |
| MIA | JJA | 14 | 1 | 225 | 1 | 0.444% | 2.474% | 4 | 0 | 38 | 16.889% | 22.331% | 40 | 1.679% |
| MIA | JJA | 15 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 15 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 16 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 16 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 17 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 17 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 18 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 18 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 19 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 19 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 20 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 20 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 21 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 21 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 22 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 22 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | JJA | 23 | 0 | 227 | 85 | 37.445% | 43.901% | 0 | 85 | 85 | 37.445% | 43.901% | 8 | 1.664% |
| MIA | JJA | 23 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 30 | 13.453% | 18.555% | 43 | 1.693% |
| MIA | MAM | 00 | 0 | 305 | 304 | 99.672% | 99.942% | 303 | 1 | 304 | 99.672% | 99.942% | 0 | 1.244% |
| MIA | MAM | 00 | 1 | 145 | 145 | 100.000% | 100.000% | 145 | 0 | 145 | 100.000% | 100.000% | 0 | 2.581% |
| MIA | MAM | 01 | 0 | 302 | 301 | 99.669% | 99.942% | 300 | 1 | 301 | 99.669% | 99.942% | 0 | 1.256% |
| MIA | MAM | 01 | 1 | 148 | 148 | 100.000% | 100.000% | 147 | 1 | 148 | 100.000% | 100.000% | 0 | 2.530% |
| MIA | MAM | 02 | 0 | 302 | 301 | 99.669% | 99.942% | 300 | 1 | 301 | 99.669% | 99.942% | 0 | 1.256% |
| MIA | MAM | 02 | 1 | 148 | 148 | 100.000% | 100.000% | 147 | 1 | 148 | 100.000% | 100.000% | 0 | 2.530% |
| MIA | MAM | 03 | 0 | 304 | 303 | 99.671% | 99.942% | 302 | 1 | 303 | 99.671% | 99.942% | 0 | 1.248% |
| MIA | MAM | 03 | 1 | 146 | 146 | 100.000% | 100.000% | 145 | 1 | 146 | 100.000% | 100.000% | 0 | 2.564% |
| MIA | MAM | 04 | 0 | 301 | 300 | 99.668% | 99.941% | 299 | 1 | 300 | 99.668% | 99.941% | 0 | 1.260% |
| MIA | MAM | 04 | 1 | 149 | 148 | 99.329% | 99.881% | 147 | 1 | 149 | 100.000% | 100.000% | 0 | 2.513% |
| MIA | MAM | 05 | 0 | 306 | 305 | 99.673% | 99.942% | 304 | 1 | 305 | 99.673% | 99.942% | 0 | 1.240% |
| MIA | MAM | 05 | 1 | 144 | 143 | 99.306% | 99.877% | 142 | 1 | 144 | 100.000% | 100.000% | 0 | 2.598% |
| MIA | MAM | 06 | 0 | 301 | 300 | 99.668% | 99.941% | 299 | 1 | 300 | 99.668% | 99.941% | 0 | 1.260% |
| MIA | MAM | 06 | 1 | 149 | 148 | 99.329% | 99.881% | 147 | 1 | 149 | 100.000% | 100.000% | 0 | 2.513% |
| MIA | MAM | 07 | 0 | 290 | 288 | 99.310% | 99.811% | 287 | 1 | 288 | 99.310% | 99.811% | 0 | 1.307% |
| MIA | MAM | 07 | 1 | 160 | 160 | 100.000% | 100.000% | 159 | 1 | 160 | 100.000% | 100.000% | 0 | 2.345% |
| MIA | MAM | 08 | 0 | 290 | 288 | 99.310% | 99.811% | 286 | 2 | 288 | 99.310% | 99.811% | 0 | 1.307% |
| MIA | MAM | 08 | 1 | 160 | 158 | 98.750% | 99.657% | 157 | 1 | 160 | 100.000% | 100.000% | 0 | 2.345% |
| MIA | MAM | 09 | 0 | 220 | 211 | 95.909% | 97.833% | 206 | 5 | 211 | 95.909% | 97.833% | 0 | 1.716% |
| MIA | MAM | 09 | 1 | 230 | 210 | 91.304% | 94.300% | 211 | 7 | 226 | 98.261% | 99.322% | 0 | 1.643% |
| MIA | MAM | 10 | 0 | 190 | 171 | 90.000% | 93.504% | 161 | 10 | 171 | 90.000% | 93.504% | 1 | 1.982% |
| MIA | MAM | 10 | 1 | 260 | 175 | 67.308% | 72.722% | 187 | 9 | 229 | 88.077% | 91.472% | 3 | 1.456% |
| MIA | MAM | 11 | 0 | 162 | 125 | 77.160% | 82.951% | 105 | 20 | 125 | 77.160% | 82.951% | 5 | 2.316% |
| MIA | MAM | 11 | 1 | 288 | 93 | 32.292% | 37.894% | 116 | 9 | 204 | 70.833% | 75.781% | 10 | 1.316% |
| MIA | MAM | 12 | 0 | 157 | 93 | 59.236% | 66.612% | 59 | 34 | 93 | 59.236% | 66.612% | 16 | 2.388% |
| MIA | MAM | 12 | 1 | 293 | 39 | 13.311% | 17.679% | 53 | 4 | 155 | 52.901% | 58.542% | 31 | 1.294% |
| MIA | MAM | 13 | 0 | 169 | 72 | 42.604% | 50.142% | 35 | 38 | 72 | 42.604% | 50.142% | 20 | 2.223% |
| MIA | MAM | 13 | 1 | 281 | 11 | 3.915% | 6.873% | 12 | 3 | 104 | 37.011% | 42.796% | 47 | 1.349% |
| MIA | MAM | 14 | 0 | 160 | 53 | 33.125% | 40.738% | 13 | 40 | 53 | 33.125% | 40.738% | 21 | 2.345% |
| MIA | MAM | 14 | 1 | 290 | 2 | 0.690% | 2.479% | 2 | 2 | 90 | 31.034% | 36.578% | 50 | 1.307% |
| MIA | MAM | 15 | 0 | 158 | 42 | 26.582% | 33.967% | 2 | 40 | 42 | 26.582% | 33.967% | 25 | 2.374% |
| MIA | MAM | 15 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 88 | 30.137% | 35.630% | 52 | 1.298% |
| MIA | MAM | 16 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 16 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 17 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 17 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 18 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 18 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 19 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 19 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 20 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 20 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 21 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 21 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 22 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 22 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | MAM | 23 | 0 | 158 | 40 | 25.316% | 32.627% | 0 | 40 | 40 | 25.316% | 32.627% | 25 | 2.374% |
| MIA | MAM | 23 | 1 | 292 | 2 | 0.685% | 2.463% | 0 | 2 | 86 | 29.452% | 34.920% | 52 | 1.298% |
| MIA | SON | 00 | 0 | 316 | 311 | 98.418% | 99.322% | 311 | 0 | 311 | 98.418% | 99.322% | 2 | 1.201% |
| MIA | SON | 00 | 1 | 132 | 131 | 99.242% | 99.866% | 131 | 0 | 132 | 100.000% | 100.000% | 0 | 2.828% |
| MIA | SON | 01 | 0 | 316 | 311 | 98.418% | 99.322% | 311 | 0 | 311 | 98.418% | 99.322% | 2 | 1.201% |
| MIA | SON | 01 | 1 | 132 | 131 | 99.242% | 99.866% | 131 | 0 | 132 | 100.000% | 100.000% | 0 | 2.828% |
| MIA | SON | 02 | 0 | 313 | 308 | 98.403% | 99.316% | 308 | 0 | 308 | 98.403% | 99.316% | 2 | 1.212% |
| MIA | SON | 02 | 1 | 135 | 134 | 99.259% | 99.869% | 134 | 0 | 135 | 100.000% | 100.000% | 0 | 2.767% |
| MIA | SON | 03 | 0 | 314 | 309 | 98.408% | 99.318% | 309 | 0 | 309 | 98.408% | 99.318% | 2 | 1.209% |
| MIA | SON | 03 | 1 | 134 | 133 | 99.254% | 99.868% | 133 | 0 | 134 | 100.000% | 100.000% | 0 | 2.787% |
| MIA | SON | 04 | 0 | 310 | 305 | 98.387% | 99.309% | 305 | 0 | 305 | 98.387% | 99.309% | 2 | 1.224% |
| MIA | SON | 04 | 1 | 138 | 137 | 99.275% | 99.872% | 137 | 0 | 138 | 100.000% | 100.000% | 0 | 2.708% |
| MIA | SON | 05 | 0 | 312 | 306 | 98.077% | 99.116% | 306 | 0 | 306 | 98.077% | 99.116% | 3 | 1.216% |
| MIA | SON | 05 | 1 | 136 | 135 | 99.265% | 99.870% | 135 | 0 | 136 | 100.000% | 100.000% | 0 | 2.747% |
| MIA | SON | 06 | 0 | 313 | 307 | 98.083% | 99.119% | 307 | 0 | 307 | 98.083% | 99.119% | 3 | 1.212% |
| MIA | SON | 06 | 1 | 135 | 134 | 99.259% | 99.869% | 134 | 0 | 135 | 100.000% | 100.000% | 0 | 2.767% |
| MIA | SON | 07 | 0 | 260 | 254 | 97.692% | 98.938% | 254 | 0 | 254 | 97.692% | 98.938% | 3 | 1.456% |
| MIA | SON | 07 | 1 | 188 | 186 | 98.936% | 99.708% | 186 | 0 | 188 | 100.000% | 100.000% | 0 | 2.002% |
| MIA | SON | 08 | 0 | 208 | 201 | 96.635% | 98.360% | 201 | 0 | 201 | 96.635% | 98.360% | 4 | 1.813% |
| MIA | SON | 08 | 1 | 240 | 234 | 97.500% | 98.849% | 234 | 1 | 238 | 99.167% | 99.771% | 1 | 1.575% |
| MIA | SON | 09 | 0 | 156 | 145 | 92.949% | 96.017% | 145 | 0 | 145 | 92.949% | 96.017% | 4 | 2.403% |
| MIA | SON | 09 | 1 | 292 | 238 | 81.507% | 85.541% | 248 | 6 | 276 | 94.521% | 96.599% | 1 | 1.298% |
| MIA | SON | 10 | 0 | 144 | 118 | 81.944% | 87.370% | 113 | 5 | 118 | 81.944% | 87.370% | 6 | 2.598% |
| MIA | SON | 10 | 1 | 304 | 162 | 53.289% | 58.822% | 170 | 18 | 250 | 82.237% | 86.123% | 12 | 1.248% |
| MIA | SON | 11 | 0 | 158 | 104 | 65.823% | 72.764% | 79 | 25 | 104 | 65.823% | 72.764% | 6 | 2.374% |
| MIA | SON | 11 | 1 | 290 | 86 | 29.655% | 35.150% | 100 | 8 | 183 | 63.103% | 68.452% | 27 | 1.307% |
| MIA | SON | 12 | 0 | 163 | 72 | 44.172% | 51.842% | 39 | 33 | 72 | 44.172% | 51.842% | 10 | 2.302% |
| MIA | SON | 12 | 1 | 285 | 31 | 10.877% | 15.026% | 42 | 6 | 124 | 43.509% | 49.313% | 43 | 1.330% |
| MIA | SON | 13 | 0 | 174 | 64 | 36.782% | 44.160% | 21 | 43 | 64 | 36.782% | 44.160% | 13 | 2.160% |
| MIA | SON | 13 | 1 | 274 | 6 | 2.190% | 4.694% | 11 | 1 | 88 | 32.117% | 37.860% | 56 | 1.383% |
| MIA | SON | 14 | 0 | 170 | 49 | 28.824% | 36.041% | 5 | 44 | 49 | 28.824% | 36.041% | 15 | 2.210% |
| MIA | SON | 14 | 1 | 278 | 2 | 0.719% | 2.585% | 3 | 0 | 73 | 26.259% | 31.730% | 63 | 1.363% |
| MIA | SON | 15 | 0 | 170 | 46 | 27.059% | 34.189% | 2 | 44 | 46 | 27.059% | 34.189% | 16 | 2.210% |
| MIA | SON | 15 | 1 | 278 | 0 | 0.000% | 1.363% | 1 | 0 | 70 | 25.180% | 30.597% | 63 | 1.363% |
| MIA | SON | 16 | 0 | 170 | 46 | 27.059% | 34.189% | 2 | 44 | 46 | 27.059% | 34.189% | 16 | 2.210% |
| MIA | SON | 16 | 1 | 278 | 0 | 0.000% | 1.363% | 0 | 0 | 69 | 24.820% | 30.218% | 64 | 1.363% |
| MIA | SON | 17 | 0 | 169 | 45 | 26.627% | 33.757% | 1 | 44 | 45 | 26.627% | 33.757% | 16 | 2.223% |
| MIA | SON | 17 | 1 | 279 | 0 | 0.000% | 1.358% | 0 | 0 | 69 | 24.731% | 30.114% | 64 | 1.358% |
| MIA | SON | 18 | 0 | 169 | 45 | 26.627% | 33.757% | 1 | 44 | 45 | 26.627% | 33.757% | 16 | 2.223% |
| MIA | SON | 18 | 1 | 279 | 0 | 0.000% | 1.358% | 0 | 0 | 69 | 24.731% | 30.114% | 64 | 1.358% |
| MIA | SON | 19 | 0 | 169 | 45 | 26.627% | 33.757% | 1 | 44 | 45 | 26.627% | 33.757% | 16 | 2.223% |
| MIA | SON | 19 | 1 | 279 | 0 | 0.000% | 1.358% | 0 | 0 | 69 | 24.731% | 30.114% | 64 | 1.358% |
| MIA | SON | 20 | 0 | 169 | 45 | 26.627% | 33.757% | 1 | 44 | 45 | 26.627% | 33.757% | 16 | 2.223% |
| MIA | SON | 20 | 1 | 279 | 0 | 0.000% | 1.358% | 0 | 0 | 69 | 24.731% | 30.114% | 64 | 1.358% |
| MIA | SON | 21 | 0 | 168 | 44 | 26.190% | 33.318% | 0 | 44 | 44 | 26.190% | 33.318% | 16 | 2.235% |
| MIA | SON | 21 | 1 | 280 | 0 | 0.000% | 1.353% | 0 | 0 | 69 | 24.643% | 30.011% | 64 | 1.353% |
| MIA | SON | 22 | 0 | 168 | 44 | 26.190% | 33.318% | 0 | 44 | 44 | 26.190% | 33.318% | 16 | 2.235% |
| MIA | SON | 22 | 1 | 280 | 0 | 0.000% | 1.353% | 0 | 0 | 69 | 24.643% | 30.011% | 64 | 1.353% |
| MIA | SON | 23 | 0 | 168 | 44 | 26.190% | 33.318% | 0 | 44 | 44 | 26.190% | 33.318% | 16 | 2.235% |
| MIA | SON | 23 | 1 | 280 | 0 | 0.000% | 1.353% | 0 | 0 | 69 | 24.643% | 30.011% | 64 | 1.353% |
| NYC | DJF | 00 | 0 | 209 | 197 | 94.258% | 96.685% | 179 | 18 | 197 | 94.258% | 96.685% | 0 | 1.805% |
| NYC | DJF | 00 | 1 | 212 | 190 | 89.623% | 93.047% | 181 | 9 | 204 | 96.226% | 98.076% | 0 | 1.780% |
| NYC | DJF | 01 | 0 | 205 | 193 | 94.146% | 96.620% | 175 | 18 | 193 | 94.146% | 96.620% | 0 | 1.839% |
| NYC | DJF | 01 | 1 | 216 | 190 | 87.963% | 91.652% | 179 | 11 | 206 | 95.370% | 97.466% | 0 | 1.747% |
| NYC | DJF | 02 | 0 | 205 | 192 | 93.659% | 96.257% | 173 | 19 | 192 | 93.659% | 96.257% | 0 | 1.839% |
| NYC | DJF | 02 | 1 | 216 | 188 | 87.037% | 90.877% | 178 | 10 | 204 | 94.444% | 96.794% | 0 | 1.747% |
| NYC | DJF | 03 | 0 | 206 | 191 | 92.718% | 95.538% | 171 | 20 | 191 | 92.718% | 95.538% | 0 | 1.831% |
| NYC | DJF | 03 | 1 | 215 | 188 | 87.442% | 91.224% | 179 | 9 | 203 | 94.419% | 96.779% | 0 | 1.755% |
| NYC | DJF | 04 | 0 | 204 | 188 | 92.157% | 95.115% | 168 | 20 | 188 | 92.157% | 95.115% | 0 | 1.848% |
| NYC | DJF | 04 | 1 | 217 | 187 | 86.175% | 90.141% | 178 | 9 | 205 | 94.470% | 96.809% | 0 | 1.739% |
| NYC | DJF | 05 | 0 | 201 | 184 | 91.542% | 94.653% | 164 | 20 | 184 | 91.542% | 94.653% | 0 | 1.875% |
| NYC | DJF | 05 | 1 | 220 | 188 | 85.455% | 89.505% | 179 | 9 | 205 | 93.182% | 95.825% | 0 | 1.716% |
| NYC | DJF | 06 | 0 | 196 | 178 | 90.816% | 94.112% | 158 | 20 | 178 | 90.816% | 94.112% | 0 | 1.922% |
| NYC | DJF | 06 | 1 | 225 | 191 | 84.889% | 88.980% | 182 | 9 | 208 | 92.444% | 95.229% | 0 | 1.679% |
| NYC | DJF | 07 | 0 | 207 | 189 | 91.304% | 94.429% | 168 | 21 | 189 | 91.304% | 94.429% | 0 | 1.822% |
| NYC | DJF | 07 | 1 | 214 | 178 | 83.178% | 87.594% | 169 | 9 | 197 | 92.056% | 94.981% | 0 | 1.763% |
| NYC | DJF | 08 | 0 | 202 | 182 | 90.099% | 93.499% | 161 | 21 | 182 | 90.099% | 93.499% | 0 | 1.866% |
| NYC | DJF | 08 | 1 | 219 | 180 | 82.192% | 86.691% | 171 | 9 | 200 | 91.324% | 94.376% | 0 | 1.724% |
| NYC | DJF | 09 | 0 | 200 | 180 | 90.000% | 93.433% | 159 | 21 | 180 | 90.000% | 93.433% | 0 | 1.885% |
| NYC | DJF | 09 | 1 | 221 | 177 | 80.090% | 84.821% | 166 | 11 | 201 | 90.950% | 94.065% | 0 | 1.709% |
| NYC | DJF | 10 | 0 | 216 | 193 | 89.352% | 92.799% | 169 | 24 | 193 | 89.352% | 92.799% | 0 | 1.747% |
| NYC | DJF | 10 | 1 | 205 | 157 | 76.585% | 81.860% | 145 | 12 | 184 | 89.756% | 93.202% | 0 | 1.839% |
| NYC | DJF | 11 | 0 | 200 | 172 | 86.000% | 90.133% | 142 | 30 | 172 | 86.000% | 90.133% | 0 | 1.885% |
| NYC | DJF | 11 | 1 | 221 | 147 | 66.516% | 72.409% | 125 | 22 | 197 | 89.140% | 92.593% | 0 | 1.709% |
| NYC | DJF | 12 | 0 | 217 | 172 | 79.263% | 84.125% | 127 | 45 | 172 | 79.263% | 84.125% | 0 | 1.739% |
| NYC | DJF | 12 | 1 | 204 | 92 | 45.098% | 51.954% | 72 | 20 | 164 | 80.392% | 85.257% | 0 | 1.848% |
| NYC | DJF | 13 | 0 | 193 | 128 | 66.321% | 72.613% | 72 | 56 | 128 | 66.321% | 72.613% | 0 | 1.952% |
| NYC | DJF | 13 | 1 | 228 | 65 | 28.509% | 34.687% | 45 | 20 | 166 | 72.807% | 78.169% | 0 | 1.657% |
| NYC | DJF | 14 | 0 | 207 | 118 | 57.005% | 63.561% | 47 | 71 | 118 | 57.005% | 63.561% | 0 | 1.822% |
| NYC | DJF | 14 | 1 | 214 | 32 | 14.953% | 20.347% | 21 | 11 | 129 | 60.280% | 66.599% | 0 | 1.763% |
| NYC | DJF | 15 | 0 | 197 | 99 | 50.254% | 57.164% | 26 | 73 | 99 | 50.254% | 57.164% | 0 | 1.913% |
| NYC | DJF | 15 | 1 | 224 | 30 | 13.393% | 18.475% | 20 | 10 | 124 | 55.357% | 61.722% | 0 | 1.686% |
| NYC | DJF | 16 | 0 | 199 | 100 | 50.251% | 57.127% | 26 | 74 | 100 | 50.251% | 57.127% | 0 | 1.894% |
| NYC | DJF | 16 | 1 | 222 | 26 | 11.712% | 16.607% | 14 | 12 | 120 | 54.054% | 60.485% | 0 | 1.701% |
| NYC | DJF | 17 | 0 | 203 | 102 | 50.246% | 57.056% | 25 | 77 | 102 | 50.246% | 57.056% | 0 | 1.857% |
| NYC | DJF | 17 | 1 | 218 | 21 | 9.633% | 14.277% | 12 | 9 | 116 | 53.211% | 59.722% | 0 | 1.732% |
| NYC | DJF | 18 | 0 | 204 | 100 | 49.020% | 55.834% | 22 | 78 | 100 | 49.020% | 55.834% | 0 | 1.848% |
| NYC | DJF | 18 | 1 | 217 | 21 | 9.677% | 14.341% | 12 | 9 | 114 | 52.535% | 59.077% | 0 | 1.739% |
| NYC | DJF | 19 | 0 | 202 | 97 | 48.020% | 54.882% | 17 | 80 | 97 | 48.020% | 54.882% | 0 | 1.866% |
| NYC | DJF | 19 | 1 | 219 | 18 | 8.219% | 12.617% | 11 | 7 | 112 | 51.142% | 57.685% | 0 | 1.724% |
| NYC | DJF | 20 | 0 | 204 | 95 | 46.569% | 53.414% | 14 | 81 | 95 | 46.569% | 53.414% | 0 | 1.848% |
| NYC | DJF | 20 | 1 | 217 | 16 | 7.373% | 11.640% | 10 | 6 | 108 | 49.770% | 56.368% | 0 | 1.739% |
| NYC | DJF | 21 | 0 | 205 | 96 | 46.829% | 53.655% | 14 | 82 | 96 | 46.829% | 53.655% | 0 | 1.839% |
| NYC | DJF | 21 | 1 | 216 | 12 | 5.556% | 9.458% | 6 | 6 | 106 | 49.074% | 55.699% | 0 | 1.747% |
| NYC | DJF | 22 | 0 | 205 | 94 | 45.854% | 52.688% | 12 | 82 | 94 | 45.854% | 52.688% | 0 | 1.839% |
| NYC | DJF | 22 | 1 | 216 | 6 | 2.778% | 5.927% | 0 | 6 | 104 | 48.148% | 54.785% | 0 | 1.747% |
| NYC | DJF | 23 | 0 | 205 | 83 | 40.488% | 47.322% | 0 | 83 | 83 | 40.488% | 47.322% | 0 | 1.839% |
| NYC | DJF | 23 | 1 | 216 | 5 | 2.315% | 5.303% | 0 | 5 | 97 | 44.907% | 51.572% | 0 | 1.747% |
| NYC | JJA | 00 | 0 | 216 | 214 | 99.074% | 99.746% | 212 | 2 | 214 | 99.074% | 99.746% | 0 | 1.747% |
| NYC | JJA | 00 | 1 | 230 | 224 | 97.391% | 98.799% | 220 | 4 | 226 | 98.261% | 99.322% | 0 | 1.643% |
| NYC | JJA | 01 | 0 | 218 | 216 | 99.083% | 99.748% | 214 | 2 | 216 | 99.083% | 99.748% | 0 | 1.732% |
| NYC | JJA | 01 | 1 | 228 | 221 | 96.930% | 98.505% | 216 | 5 | 224 | 98.246% | 99.316% | 0 | 1.657% |
| NYC | JJA | 02 | 0 | 224 | 222 | 99.107% | 99.755% | 220 | 2 | 222 | 99.107% | 99.755% | 0 | 1.686% |
| NYC | JJA | 02 | 1 | 222 | 215 | 96.847% | 98.464% | 210 | 5 | 218 | 98.198% | 99.297% | 0 | 1.701% |
| NYC | JJA | 03 | 0 | 224 | 222 | 99.107% | 99.755% | 220 | 2 | 222 | 99.107% | 99.755% | 0 | 1.686% |
| NYC | JJA | 03 | 1 | 222 | 215 | 96.847% | 98.464% | 210 | 5 | 218 | 98.198% | 99.297% | 0 | 1.701% |
| NYC | JJA | 04 | 0 | 226 | 223 | 98.673% | 99.548% | 221 | 2 | 223 | 98.673% | 99.548% | 0 | 1.671% |
| NYC | JJA | 04 | 1 | 220 | 214 | 97.273% | 98.744% | 209 | 5 | 216 | 98.182% | 99.291% | 0 | 1.716% |
| NYC | JJA | 05 | 0 | 222 | 219 | 98.649% | 99.539% | 217 | 2 | 219 | 98.649% | 99.539% | 0 | 1.701% |
| NYC | JJA | 05 | 1 | 224 | 218 | 97.321% | 98.767% | 212 | 6 | 220 | 98.214% | 99.303% | 0 | 1.686% |
| NYC | JJA | 06 | 0 | 215 | 212 | 98.605% | 99.524% | 210 | 2 | 212 | 98.605% | 99.524% | 0 | 1.755% |
| NYC | JJA | 06 | 1 | 231 | 225 | 97.403% | 98.804% | 219 | 6 | 227 | 98.268% | 99.325% | 0 | 1.636% |
| NYC | JJA | 07 | 0 | 221 | 218 | 98.643% | 99.537% | 214 | 4 | 218 | 98.643% | 99.537% | 0 | 1.709% |
| NYC | JJA | 07 | 1 | 225 | 219 | 97.333% | 98.772% | 215 | 4 | 221 | 98.222% | 99.307% | 0 | 1.679% |
| NYC | JJA | 08 | 0 | 204 | 201 | 98.529% | 99.499% | 197 | 4 | 201 | 98.529% | 99.499% | 0 | 1.848% |
| NYC | JJA | 08 | 1 | 242 | 235 | 97.107% | 98.592% | 229 | 6 | 238 | 98.347% | 99.355% | 0 | 1.563% |
| NYC | JJA | 09 | 0 | 213 | 209 | 98.122% | 99.267% | 202 | 7 | 209 | 98.122% | 99.267% | 0 | 1.772% |
| NYC | JJA | 09 | 1 | 233 | 222 | 95.279% | 97.344% | 215 | 7 | 229 | 98.283% | 99.330% | 0 | 1.622% |
| NYC | JJA | 10 | 0 | 220 | 213 | 96.818% | 98.450% | 197 | 16 | 213 | 96.818% | 98.450% | 0 | 1.716% |
| NYC | JJA | 10 | 1 | 226 | 204 | 90.265% | 93.483% | 180 | 24 | 219 | 96.903% | 98.492% | 0 | 1.671% |
| NYC | JJA | 11 | 0 | 228 | 219 | 96.053% | 97.910% | 162 | 57 | 219 | 96.053% | 97.910% | 0 | 1.657% |
| NYC | JJA | 11 | 1 | 218 | 159 | 72.936% | 78.399% | 100 | 59 | 204 | 93.578% | 96.136% | 0 | 1.732% |
| NYC | JJA | 12 | 0 | 221 | 195 | 88.235% | 91.844% | 88 | 107 | 195 | 88.235% | 91.844% | 0 | 1.709% |
| NYC | JJA | 12 | 1 | 225 | 100 | 44.444% | 50.976% | 50 | 50 | 196 | 87.111% | 90.874% | 0 | 1.679% |
| NYC | JJA | 13 | 0 | 233 | 189 | 81.116% | 85.621% | 60 | 129 | 189 | 81.116% | 85.621% | 0 | 1.622% |
| NYC | JJA | 13 | 1 | 213 | 65 | 30.516% | 37.000% | 23 | 42 | 171 | 80.282% | 85.068% | 0 | 1.772% |
| NYC | JJA | 14 | 0 | 247 | 181 | 73.279% | 78.410% | 41 | 140 | 181 | 73.279% | 78.410% | 0 | 1.531% |
| NYC | JJA | 14 | 1 | 199 | 40 | 20.101% | 26.211% | 5 | 35 | 148 | 74.372% | 79.936% | 0 | 1.894% |
| NYC | JJA | 15 | 0 | 232 | 161 | 69.397% | 74.971% | 12 | 149 | 161 | 69.397% | 74.971% | 0 | 1.629% |
| NYC | JJA | 15 | 1 | 214 | 35 | 16.355% | 21.896% | 1 | 34 | 154 | 71.963% | 77.553% | 0 | 1.763% |
| NYC | JJA | 16 | 0 | 232 | 153 | 65.948% | 71.742% | 1 | 152 | 153 | 65.948% | 71.742% | 0 | 1.629% |
| NYC | JJA | 16 | 1 | 214 | 32 | 14.953% | 20.347% | 0 | 32 | 150 | 70.093% | 75.829% | 0 | 1.763% |
| NYC | JJA | 17 | 0 | 237 | 155 | 65.401% | 71.168% | 1 | 154 | 155 | 65.401% | 71.168% | 0 | 1.595% |
| NYC | JJA | 17 | 1 | 209 | 30 | 14.354% | 19.752% | 0 | 30 | 145 | 69.378% | 75.230% | 0 | 1.805% |
| NYC | JJA | 18 | 0 | 237 | 155 | 65.401% | 71.168% | 1 | 154 | 155 | 65.401% | 71.168% | 0 | 1.595% |
| NYC | JJA | 18 | 1 | 209 | 30 | 14.354% | 19.752% | 0 | 30 | 145 | 69.378% | 75.230% | 0 | 1.805% |
| NYC | JJA | 19 | 0 | 237 | 155 | 65.401% | 71.168% | 1 | 154 | 155 | 65.401% | 71.168% | 0 | 1.595% |
| NYC | JJA | 19 | 1 | 209 | 30 | 14.354% | 19.752% | 0 | 30 | 145 | 69.378% | 75.230% | 0 | 1.805% |
| NYC | JJA | 20 | 0 | 237 | 155 | 65.401% | 71.168% | 1 | 154 | 155 | 65.401% | 71.168% | 0 | 1.595% |
| NYC | JJA | 20 | 1 | 209 | 30 | 14.354% | 19.752% | 0 | 30 | 145 | 69.378% | 75.230% | 0 | 1.805% |
| NYC | JJA | 21 | 0 | 237 | 155 | 65.401% | 71.168% | 1 | 154 | 155 | 65.401% | 71.168% | 0 | 1.595% |
| NYC | JJA | 21 | 1 | 209 | 30 | 14.354% | 19.752% | 0 | 30 | 145 | 69.378% | 75.230% | 0 | 1.805% |
| NYC | JJA | 22 | 0 | 236 | 154 | 65.254% | 71.041% | 0 | 154 | 154 | 65.254% | 71.041% | 0 | 1.602% |
| NYC | JJA | 22 | 1 | 210 | 30 | 14.286% | 19.661% | 0 | 30 | 145 | 69.048% | 74.911% | 0 | 1.796% |
| NYC | JJA | 23 | 0 | 236 | 154 | 65.254% | 71.041% | 0 | 154 | 154 | 65.254% | 71.041% | 0 | 1.602% |
| NYC | JJA | 23 | 1 | 210 | 30 | 14.286% | 19.661% | 0 | 30 | 145 | 69.048% | 74.911% | 0 | 1.796% |
| NYC | MAM | 00 | 0 | 209 | 201 | 96.172% | 98.048% | 192 | 9 | 201 | 96.172% | 98.048% | 0 | 1.805% |
| NYC | MAM | 00 | 1 | 222 | 204 | 91.892% | 94.810% | 197 | 7 | 215 | 96.847% | 98.464% | 0 | 1.701% |
| NYC | MAM | 01 | 0 | 216 | 208 | 96.296% | 98.112% | 199 | 9 | 208 | 96.296% | 98.112% | 0 | 1.747% |
| NYC | MAM | 01 | 1 | 215 | 195 | 90.698% | 93.897% | 187 | 8 | 207 | 96.279% | 98.103% | 0 | 1.755% |
| NYC | MAM | 02 | 0 | 214 | 205 | 95.794% | 97.772% | 196 | 9 | 205 | 95.794% | 97.772% | 0 | 1.763% |
| NYC | MAM | 02 | 1 | 217 | 198 | 91.244% | 94.323% | 190 | 8 | 209 | 96.313% | 98.120% | 0 | 1.739% |
| NYC | MAM | 03 | 0 | 217 | 208 | 95.853% | 97.803% | 198 | 10 | 208 | 95.853% | 97.803% | 0 | 1.739% |
| NYC | MAM | 03 | 1 | 214 | 194 | 90.654% | 93.868% | 187 | 7 | 206 | 96.262% | 98.094% | 0 | 1.763% |
| NYC | MAM | 04 | 0 | 211 | 202 | 95.735% | 97.740% | 192 | 10 | 202 | 95.735% | 97.740% | 0 | 1.788% |
| NYC | MAM | 04 | 1 | 220 | 200 | 90.909% | 94.038% | 193 | 7 | 212 | 96.364% | 98.146% | 0 | 1.716% |
| NYC | MAM | 05 | 0 | 219 | 209 | 95.434% | 97.501% | 199 | 10 | 209 | 95.434% | 97.501% | 0 | 1.724% |
| NYC | MAM | 05 | 1 | 212 | 193 | 91.038% | 94.187% | 186 | 7 | 204 | 96.226% | 98.076% | 0 | 1.780% |
| NYC | MAM | 06 | 0 | 225 | 215 | 95.556% | 97.568% | 205 | 10 | 215 | 95.556% | 97.568% | 0 | 1.679% |
| NYC | MAM | 06 | 1 | 206 | 186 | 90.291% | 93.627% | 179 | 7 | 197 | 95.631% | 97.685% | 0 | 1.831% |
| NYC | MAM | 07 | 0 | 210 | 198 | 94.286% | 96.701% | 188 | 10 | 198 | 94.286% | 96.701% | 0 | 1.796% |
| NYC | MAM | 07 | 1 | 221 | 202 | 91.403% | 94.427% | 193 | 9 | 212 | 95.928% | 97.843% | 0 | 1.709% |
| NYC | MAM | 08 | 0 | 218 | 205 | 94.037% | 96.482% | 193 | 12 | 205 | 94.037% | 96.482% | 0 | 1.732% |
| NYC | MAM | 08 | 1 | 213 | 192 | 90.141% | 93.461% | 182 | 10 | 204 | 95.775% | 97.761% | 0 | 1.772% |
| NYC | MAM | 09 | 0 | 201 | 185 | 92.040% | 95.041% | 170 | 15 | 185 | 92.040% | 95.041% | 0 | 1.875% |
| NYC | MAM | 09 | 1 | 230 | 208 | 90.435% | 93.598% | 197 | 11 | 221 | 96.087% | 97.928% | 0 | 1.643% |
| NYC | MAM | 10 | 0 | 231 | 212 | 91.775% | 94.671% | 190 | 22 | 212 | 91.775% | 94.671% | 0 | 1.636% |
| NYC | MAM | 10 | 1 | 200 | 169 | 84.500% | 88.860% | 151 | 18 | 189 | 94.500% | 96.901% | 0 | 1.885% |
| NYC | MAM | 11 | 0 | 227 | 203 | 89.427% | 92.792% | 163 | 40 | 203 | 89.427% | 92.792% | 0 | 1.664% |
| NYC | MAM | 11 | 1 | 204 | 156 | 76.471% | 81.769% | 127 | 29 | 189 | 92.647% | 95.494% | 0 | 1.848% |
| NYC | MAM | 12 | 0 | 222 | 184 | 82.883% | 87.268% | 116 | 68 | 184 | 82.883% | 87.268% | 0 | 1.701% |
| NYC | MAM | 12 | 1 | 209 | 114 | 54.545% | 61.153% | 72 | 42 | 176 | 84.211% | 88.531% | 0 | 1.805% |
| NYC | MAM | 13 | 0 | 234 | 180 | 76.923% | 81.860% | 80 | 100 | 180 | 76.923% | 81.860% | 0 | 1.615% |
| NYC | MAM | 13 | 1 | 197 | 78 | 39.594% | 46.559% | 35 | 43 | 153 | 77.665% | 82.920% | 0 | 1.913% |
| NYC | MAM | 14 | 0 | 228 | 166 | 72.807% | 78.169% | 35 | 131 | 166 | 72.807% | 78.169% | 0 | 1.657% |
| NYC | MAM | 14 | 1 | 203 | 41 | 20.197% | 26.250% | 11 | 30 | 142 | 69.951% | 75.839% | 0 | 1.857% |
| NYC | MAM | 15 | 0 | 227 | 155 | 68.282% | 73.989% | 14 | 141 | 155 | 68.282% | 73.989% | 0 | 1.664% |
| NYC | MAM | 15 | 1 | 204 | 27 | 13.235% | 18.572% | 5 | 22 | 132 | 64.706% | 70.937% | 0 | 1.848% |
| NYC | MAM | 16 | 0 | 222 | 148 | 66.667% | 72.538% | 5 | 143 | 148 | 66.667% | 72.538% | 0 | 1.701% |
| NYC | MAM | 16 | 1 | 209 | 26 | 12.440% | 17.604% | 4 | 22 | 135 | 64.593% | 70.760% | 0 | 1.805% |
| NYC | MAM | 17 | 0 | 226 | 150 | 66.372% | 72.212% | 6 | 144 | 150 | 66.372% | 72.212% | 0 | 1.671% |
| NYC | MAM | 17 | 1 | 205 | 23 | 11.220% | 16.272% | 2 | 21 | 130 | 63.415% | 69.705% | 0 | 1.839% |
| NYC | MAM | 18 | 0 | 224 | 147 | 65.625% | 71.534% | 3 | 144 | 147 | 65.625% | 71.534% | 0 | 1.686% |
| NYC | MAM | 18 | 1 | 207 | 26 | 12.560% | 17.768% | 5 | 21 | 132 | 63.768% | 70.010% | 0 | 1.822% |
| NYC | MAM | 19 | 0 | 225 | 147 | 65.333% | 71.247% | 2 | 145 | 147 | 65.333% | 71.247% | 0 | 1.679% |
| NYC | MAM | 19 | 1 | 206 | 25 | 12.136% | 17.301% | 4 | 21 | 130 | 63.107% | 69.400% | 0 | 1.831% |
| NYC | MAM | 20 | 0 | 229 | 150 | 65.502% | 71.358% | 5 | 145 | 150 | 65.502% | 71.358% | 0 | 1.650% |
| NYC | MAM | 20 | 1 | 202 | 22 | 10.891% | 15.939% | 1 | 21 | 126 | 62.376% | 68.767% | 0 | 1.866% |
| NYC | MAM | 21 | 0 | 226 | 147 | 65.044% | 70.962% | 2 | 145 | 147 | 65.044% | 70.962% | 0 | 1.671% |
| NYC | MAM | 21 | 1 | 205 | 22 | 10.732% | 15.714% | 1 | 21 | 127 | 61.951% | 68.320% | 0 | 1.839% |
| NYC | MAM | 22 | 0 | 224 | 145 | 64.732% | 70.693% | 0 | 145 | 145 | 64.732% | 70.693% | 0 | 1.686% |
| NYC | MAM | 22 | 1 | 207 | 22 | 10.628% | 15.567% | 1 | 21 | 128 | 61.836% | 68.181% | 0 | 1.822% |
| NYC | MAM | 23 | 0 | 226 | 145 | 64.159% | 70.127% | 0 | 145 | 145 | 64.159% | 70.127% | 0 | 1.671% |
| NYC | MAM | 23 | 1 | 205 | 21 | 10.244% | 15.152% | 0 | 21 | 126 | 61.463% | 67.857% | 0 | 1.839% |
| NYC | SON | 00 | 0 | 206 | 202 | 98.058% | 99.242% | 190 | 12 | 202 | 98.058% | 99.242% | 0 | 1.831% |
| NYC | SON | 00 | 1 | 232 | 212 | 91.379% | 94.350% | 209 | 3 | 227 | 97.845% | 99.076% | 0 | 1.629% |
| NYC | SON | 01 | 0 | 210 | 204 | 97.143% | 98.684% | 192 | 12 | 204 | 97.143% | 98.684% | 0 | 1.796% |
| NYC | SON | 01 | 1 | 228 | 207 | 90.789% | 93.897% | 204 | 3 | 221 | 96.930% | 98.505% | 0 | 1.657% |
| NYC | SON | 02 | 0 | 211 | 205 | 97.156% | 98.690% | 193 | 12 | 205 | 97.156% | 98.690% | 0 | 1.788% |
| NYC | SON | 02 | 1 | 227 | 206 | 90.749% | 93.870% | 203 | 3 | 220 | 96.916% | 98.498% | 0 | 1.664% |
| NYC | SON | 03 | 0 | 216 | 210 | 97.222% | 98.721% | 197 | 13 | 210 | 97.222% | 98.721% | 0 | 1.747% |
| NYC | SON | 03 | 1 | 222 | 201 | 90.541% | 93.730% | 199 | 2 | 215 | 96.847% | 98.464% | 0 | 1.701% |
| NYC | SON | 04 | 0 | 213 | 207 | 97.183% | 98.703% | 194 | 13 | 207 | 97.183% | 98.703% | 0 | 1.772% |
| NYC | SON | 04 | 1 | 225 | 204 | 90.667% | 93.814% | 202 | 2 | 218 | 96.889% | 98.485% | 0 | 1.679% |
| NYC | SON | 05 | 0 | 216 | 210 | 97.222% | 98.721% | 197 | 13 | 210 | 97.222% | 98.721% | 0 | 1.747% |
| NYC | SON | 05 | 1 | 222 | 200 | 90.090% | 93.364% | 198 | 2 | 215 | 96.847% | 98.464% | 0 | 1.701% |
| NYC | SON | 06 | 0 | 215 | 208 | 96.744% | 98.414% | 195 | 13 | 208 | 96.744% | 98.414% | 0 | 1.755% |
| NYC | SON | 06 | 1 | 223 | 201 | 90.135% | 93.394% | 198 | 3 | 216 | 96.861% | 98.471% | 0 | 1.693% |
| NYC | SON | 07 | 0 | 206 | 199 | 96.602% | 98.344% | 186 | 13 | 199 | 96.602% | 98.344% | 0 | 1.831% |
| NYC | SON | 07 | 1 | 232 | 210 | 90.517% | 93.654% | 207 | 3 | 225 | 96.983% | 98.531% | 0 | 1.629% |
| NYC | SON | 08 | 0 | 207 | 200 | 96.618% | 98.352% | 186 | 14 | 200 | 96.618% | 98.352% | 0 | 1.822% |
| NYC | SON | 08 | 1 | 231 | 205 | 88.745% | 92.202% | 202 | 3 | 223 | 96.537% | 98.235% | 1 | 1.636% |
| NYC | SON | 09 | 0 | 217 | 209 | 96.313% | 98.120% | 194 | 15 | 209 | 96.313% | 98.120% | 0 | 1.739% |
| NYC | SON | 09 | 1 | 221 | 188 | 85.068% | 89.166% | 185 | 3 | 213 | 96.380% | 98.155% | 1 | 1.709% |
| NYC | SON | 10 | 0 | 214 | 205 | 95.794% | 97.772% | 188 | 17 | 205 | 95.794% | 97.772% | 0 | 1.763% |
| NYC | SON | 10 | 1 | 224 | 183 | 81.696% | 86.212% | 170 | 13 | 213 | 95.089% | 97.236% | 1 | 1.686% |
| NYC | SON | 11 | 0 | 228 | 211 | 92.544% | 95.293% | 176 | 35 | 211 | 92.544% | 95.293% | 0 | 1.657% |
| NYC | SON | 11 | 1 | 210 | 128 | 60.952% | 67.297% | 99 | 29 | 192 | 91.429% | 94.510% | 1 | 1.796% |
| NYC | SON | 12 | 0 | 202 | 165 | 81.683% | 86.409% | 103 | 62 | 165 | 81.683% | 86.409% | 0 | 1.866% |
| NYC | SON | 12 | 1 | 236 | 92 | 38.983% | 45.334% | 55 | 37 | 200 | 84.746% | 88.773% | 1 | 1.602% |
| NYC | SON | 13 | 0 | 211 | 139 | 65.877% | 71.939% | 48 | 91 | 139 | 65.877% | 71.939% | 0 | 1.788% |
| NYC | SON | 13 | 1 | 227 | 40 | 17.621% | 23.104% | 21 | 19 | 165 | 72.687% | 78.070% | 1 | 1.664% |
| NYC | SON | 14 | 0 | 209 | 112 | 53.589% | 60.224% | 16 | 96 | 112 | 53.589% | 60.224% | 0 | 1.805% |
| NYC | SON | 14 | 1 | 229 | 22 | 9.607% | 14.117% | 7 | 15 | 140 | 61.135% | 67.215% | 1 | 1.650% |
| NYC | SON | 15 | 0 | 208 | 106 | 50.962% | 57.676% | 9 | 97 | 106 | 50.962% | 57.676% | 0 | 1.813% |
| NYC | SON | 15 | 1 | 230 | 19 | 8.261% | 12.541% | 5 | 14 | 134 | 58.261% | 64.447% | 1 | 1.643% |
| NYC | SON | 16 | 0 | 211 | 107 | 50.711% | 57.383% | 10 | 97 | 107 | 50.711% | 57.383% | 0 | 1.788% |
| NYC | SON | 16 | 1 | 227 | 17 | 7.489% | 11.665% | 3 | 14 | 131 | 57.709% | 63.955% | 1 | 1.664% |
| NYC | SON | 17 | 0 | 210 | 105 | 50.000% | 56.702% | 7 | 98 | 105 | 50.000% | 56.702% | 0 | 1.796% |
| NYC | SON | 17 | 1 | 228 | 15 | 6.579% | 10.570% | 2 | 13 | 129 | 56.579% | 62.851% | 1 | 1.657% |
| NYC | SON | 18 | 0 | 212 | 104 | 49.057% | 55.743% | 6 | 98 | 104 | 49.057% | 55.743% | 0 | 1.780% |
| NYC | SON | 18 | 1 | 226 | 15 | 6.637% | 10.661% | 2 | 13 | 127 | 56.195% | 62.506% | 1 | 1.671% |
| NYC | SON | 19 | 0 | 211 | 102 | 48.341% | 55.053% | 4 | 98 | 102 | 48.341% | 55.053% | 0 | 1.788% |
| NYC | SON | 19 | 1 | 227 | 15 | 6.608% | 10.615% | 2 | 13 | 127 | 55.947% | 62.253% | 1 | 1.664% |
| NYC | SON | 20 | 0 | 213 | 103 | 48.357% | 55.037% | 5 | 98 | 103 | 48.357% | 55.037% | 0 | 1.772% |
| NYC | SON | 20 | 1 | 225 | 14 | 6.222% | 10.172% | 1 | 13 | 125 | 55.556% | 61.901% | 1 | 1.679% |
| NYC | SON | 21 | 0 | 213 | 100 | 46.948% | 53.645% | 2 | 98 | 100 | 46.948% | 53.645% | 0 | 1.772% |
| NYC | SON | 21 | 1 | 225 | 16 | 7.111% | 11.238% | 2 | 14 | 124 | 55.111% | 61.470% | 1 | 1.679% |
| NYC | SON | 22 | 0 | 215 | 102 | 47.442% | 54.103% | 2 | 100 | 102 | 47.442% | 54.103% | 0 | 1.755% |
| NYC | SON | 22 | 1 | 223 | 12 | 5.381% | 9.169% | 0 | 12 | 120 | 53.812% | 60.235% | 1 | 1.693% |
| NYC | SON | 23 | 0 | 214 | 101 | 47.196% | 53.875% | 0 | 101 | 101 | 47.196% | 53.875% | 0 | 1.763% |
| NYC | SON | 23 | 1 | 224 | 12 | 5.357% | 9.129% | 0 | 12 | 120 | 53.571% | 59.987% | 1 | 1.686% |
| SFO | DJF | 00 | 0 | 139 | 132 | 94.964% | 97.539% | 129 | 3 | 132 | 94.964% | 97.539% | 3 | 2.689% |
| SFO | DJF | 00 | 1 | 306 | 291 | 95.098% | 97.007% | 291 | 0 | 299 | 97.712% | 98.888% | 2 | 1.240% |
| SFO | DJF | 01 | 0 | 136 | 127 | 93.382% | 96.480% | 123 | 4 | 127 | 93.382% | 96.480% | 3 | 2.747% |
| SFO | DJF | 01 | 1 | 309 | 290 | 93.851% | 96.029% | 290 | 0 | 300 | 97.087% | 98.460% | 2 | 1.228% |
| SFO | DJF | 02 | 0 | 132 | 122 | 92.424% | 95.833% | 118 | 4 | 122 | 92.424% | 95.833% | 4 | 2.828% |
| SFO | DJF | 02 | 1 | 313 | 292 | 93.291% | 95.570% | 292 | 0 | 303 | 96.805% | 98.256% | 2 | 1.212% |
| SFO | DJF | 03 | 0 | 135 | 125 | 92.593% | 95.927% | 121 | 4 | 125 | 92.593% | 95.927% | 4 | 2.767% |
| SFO | DJF | 03 | 1 | 310 | 289 | 93.226% | 95.527% | 289 | 0 | 300 | 96.774% | 98.239% | 2 | 1.224% |
| SFO | DJF | 04 | 0 | 140 | 128 | 91.429% | 95.029% | 124 | 4 | 128 | 91.429% | 95.029% | 6 | 2.671% |
| SFO | DJF | 04 | 1 | 305 | 284 | 93.115% | 95.453% | 284 | 0 | 295 | 96.721% | 98.210% | 2 | 1.244% |
| SFO | DJF | 05 | 0 | 146 | 134 | 91.781% | 95.236% | 130 | 4 | 134 | 91.781% | 95.236% | 6 | 2.564% |
| SFO | DJF | 05 | 1 | 299 | 277 | 92.642% | 95.091% | 277 | 0 | 288 | 96.321% | 97.934% | 2 | 1.268% |
| SFO | DJF | 06 | 0 | 150 | 138 | 92.000% | 95.365% | 134 | 4 | 138 | 92.000% | 95.365% | 6 | 2.497% |
| SFO | DJF | 06 | 1 | 295 | 273 | 92.542% | 95.024% | 273 | 0 | 284 | 96.271% | 97.905% | 2 | 1.285% |
| SFO | DJF | 07 | 0 | 147 | 134 | 91.156% | 94.759% | 130 | 4 | 134 | 91.156% | 94.759% | 6 | 2.547% |
| SFO | DJF | 07 | 1 | 298 | 276 | 92.617% | 95.074% | 276 | 0 | 287 | 96.309% | 97.927% | 2 | 1.273% |
| SFO | DJF | 08 | 0 | 167 | 152 | 91.018% | 94.481% | 148 | 4 | 152 | 91.018% | 94.481% | 6 | 2.249% |
| SFO | DJF | 08 | 1 | 278 | 256 | 92.086% | 94.716% | 256 | 0 | 267 | 96.043% | 97.776% | 2 | 1.363% |
| SFO | DJF | 09 | 0 | 167 | 148 | 88.623% | 92.594% | 144 | 4 | 148 | 88.623% | 92.594% | 9 | 2.249% |
| SFO | DJF | 09 | 1 | 278 | 249 | 89.568% | 92.638% | 253 | 0 | 265 | 95.324% | 97.247% | 3 | 1.363% |
| SFO | DJF | 10 | 0 | 185 | 158 | 85.405% | 89.772% | 153 | 5 | 158 | 85.405% | 89.772% | 12 | 2.034% |
| SFO | DJF | 10 | 1 | 260 | 218 | 83.846% | 87.821% | 218 | 6 | 244 | 93.846% | 96.177% | 3 | 1.456% |
| SFO | DJF | 11 | 0 | 220 | 183 | 83.182% | 87.545% | 173 | 10 | 183 | 83.182% | 87.545% | 14 | 1.716% |
| SFO | DJF | 11 | 1 | 225 | 170 | 75.556% | 80.711% | 169 | 9 | 202 | 89.778% | 93.091% | 6 | 1.679% |
| SFO | DJF | 12 | 0 | 240 | 174 | 72.500% | 77.761% | 156 | 18 | 174 | 72.500% | 77.761% | 20 | 1.575% |
| SFO | DJF | 12 | 1 | 205 | 126 | 61.463% | 67.857% | 122 | 11 | 163 | 79.512% | 84.470% | 8 | 1.839% |
| SFO | DJF | 13 | 0 | 257 | 141 | 54.864% | 60.832% | 110 | 32 | 141 | 54.864% | 60.832% | 43 | 1.473% |
| SFO | DJF | 13 | 1 | 188 | 69 | 36.702% | 43.794% | 69 | 8 | 116 | 61.702% | 68.351% | 11 | 2.002% |
| SFO | DJF | 14 | 0 | 273 | 115 | 42.125% | 48.051% | 70 | 46 | 115 | 42.125% | 48.051% | 52 | 1.388% |
| SFO | DJF | 14 | 1 | 172 | 32 | 18.605% | 25.083% | 31 | 8 | 72 | 41.860% | 49.332% | 17 | 2.185% |
| SFO | DJF | 15 | 0 | 274 | 74 | 27.007% | 32.556% | 22 | 54 | 74 | 27.007% | 32.556% | 63 | 1.383% |
| SFO | DJF | 15 | 1 | 171 | 13 | 7.602% | 12.571% | 14 | 1 | 47 | 27.485% | 34.616% | 24 | 2.197% |
| SFO | DJF | 16 | 0 | 276 | 66 | 23.913% | 29.282% | 12 | 55 | 66 | 23.913% | 29.282% | 68 | 1.373% |
| SFO | DJF | 16 | 1 | 169 | 7 | 4.142% | 8.302% | 6 | 2 | 37 | 21.893% | 28.715% | 28 | 2.223% |
| SFO | DJF | 17 | 0 | 274 | 60 | 21.898% | 27.165% | 6 | 55 | 60 | 21.898% | 27.165% | 71 | 1.383% |
| SFO | DJF | 17 | 1 | 171 | 7 | 4.094% | 8.208% | 5 | 2 | 35 | 20.468% | 27.132% | 29 | 2.197% |
| SFO | DJF | 18 | 0 | 274 | 61 | 22.263% | 27.553% | 5 | 56 | 61 | 22.263% | 27.553% | 70 | 1.383% |
| SFO | DJF | 18 | 1 | 171 | 6 | 3.509% | 7.443% | 5 | 1 | 34 | 19.883% | 26.498% | 30 | 2.197% |
| SFO | DJF | 19 | 0 | 275 | 61 | 22.182% | 27.457% | 5 | 56 | 61 | 22.182% | 27.457% | 71 | 1.378% |
| SFO | DJF | 19 | 1 | 170 | 4 | 2.353% | 5.893% | 3 | 1 | 32 | 18.824% | 25.364% | 30 | 2.210% |
| SFO | DJF | 20 | 0 | 276 | 61 | 22.101% | 27.361% | 4 | 57 | 61 | 22.101% | 27.361% | 72 | 1.373% |
| SFO | DJF | 20 | 1 | 169 | 3 | 1.775% | 5.088% | 3 | 0 | 31 | 18.343% | 24.859% | 30 | 2.223% |
| SFO | DJF | 21 | 0 | 277 | 62 | 22.383% | 27.650% | 5 | 57 | 62 | 22.383% | 27.650% | 72 | 1.368% |
| SFO | DJF | 21 | 1 | 168 | 1 | 0.595% | 3.294% | 1 | 0 | 29 | 17.262% | 23.691% | 30 | 2.235% |
| SFO | DJF | 22 | 0 | 276 | 60 | 21.739% | 26.975% | 3 | 57 | 60 | 21.739% | 26.975% | 72 | 1.373% |
| SFO | DJF | 22 | 1 | 169 | 1 | 0.592% | 3.275% | 0 | 1 | 29 | 17.160% | 23.558% | 30 | 2.223% |
| SFO | DJF | 23 | 0 | 275 | 58 | 21.091% | 26.294% | 0 | 58 | 58 | 21.091% | 26.294% | 72 | 1.378% |
| SFO | DJF | 23 | 1 | 170 | 0 | 0.000% | 2.210% | 0 | 0 | 28 | 16.471% | 22.775% | 30 | 2.210% |
| SFO | JJA | 00 | 0 | 327 | 327 | 100.000% | 100.000% | 327 | 0 | 327 | 100.000% | 100.000% | 0 | 1.161% |
| SFO | JJA | 00 | 1 | 119 | 119 | 100.000% | 100.000% | 119 | 0 | 119 | 100.000% | 100.000% | 0 | 3.127% |
| SFO | JJA | 01 | 0 | 323 | 323 | 100.000% | 100.000% | 323 | 0 | 323 | 100.000% | 100.000% | 0 | 1.175% |
| SFO | JJA | 01 | 1 | 123 | 123 | 100.000% | 100.000% | 123 | 0 | 123 | 100.000% | 100.000% | 0 | 3.029% |
| SFO | JJA | 02 | 0 | 324 | 324 | 100.000% | 100.000% | 324 | 0 | 324 | 100.000% | 100.000% | 0 | 1.172% |
| SFO | JJA | 02 | 1 | 122 | 122 | 100.000% | 100.000% | 122 | 0 | 122 | 100.000% | 100.000% | 0 | 3.053% |
| SFO | JJA | 03 | 0 | 326 | 326 | 100.000% | 100.000% | 326 | 0 | 326 | 100.000% | 100.000% | 0 | 1.165% |
| SFO | JJA | 03 | 1 | 120 | 120 | 100.000% | 100.000% | 120 | 0 | 120 | 100.000% | 100.000% | 0 | 3.102% |
| SFO | JJA | 04 | 0 | 327 | 327 | 100.000% | 100.000% | 327 | 0 | 327 | 100.000% | 100.000% | 0 | 1.161% |
| SFO | JJA | 04 | 1 | 119 | 119 | 100.000% | 100.000% | 119 | 0 | 119 | 100.000% | 100.000% | 0 | 3.127% |
| SFO | JJA | 05 | 0 | 299 | 299 | 100.000% | 100.000% | 299 | 0 | 299 | 100.000% | 100.000% | 0 | 1.268% |
| SFO | JJA | 05 | 1 | 147 | 147 | 100.000% | 100.000% | 147 | 0 | 147 | 100.000% | 100.000% | 0 | 2.547% |
| SFO | JJA | 06 | 0 | 324 | 324 | 100.000% | 100.000% | 324 | 0 | 324 | 100.000% | 100.000% | 0 | 1.172% |
| SFO | JJA | 06 | 1 | 122 | 122 | 100.000% | 100.000% | 122 | 0 | 122 | 100.000% | 100.000% | 0 | 3.053% |
| SFO | JJA | 07 | 0 | 328 | 328 | 100.000% | 100.000% | 328 | 0 | 328 | 100.000% | 100.000% | 0 | 1.158% |
| SFO | JJA | 07 | 1 | 118 | 116 | 98.305% | 99.534% | 116 | 0 | 117 | 99.153% | 99.850% | 0 | 3.153% |
| SFO | JJA | 08 | 0 | 262 | 261 | 99.618% | 99.933% | 261 | 0 | 261 | 99.618% | 99.933% | 0 | 1.445% |
| SFO | JJA | 08 | 1 | 184 | 180 | 97.826% | 99.151% | 181 | 2 | 183 | 99.457% | 99.904% | 0 | 2.045% |
| SFO | JJA | 09 | 0 | 203 | 200 | 98.522% | 99.496% | 198 | 2 | 200 | 98.522% | 99.496% | 0 | 1.857% |
| SFO | JJA | 09 | 1 | 243 | 233 | 95.885% | 97.750% | 233 | 3 | 239 | 98.354% | 99.358% | 1 | 1.556% |
| SFO | JJA | 10 | 0 | 161 | 155 | 96.273% | 98.281% | 149 | 6 | 155 | 96.273% | 98.281% | 1 | 2.330% |
| SFO | JJA | 10 | 1 | 285 | 235 | 82.456% | 86.432% | 234 | 13 | 264 | 92.632% | 95.130% | 7 | 1.330% |
| SFO | JJA | 11 | 0 | 145 | 117 | 80.690% | 86.288% | 95 | 22 | 117 | 80.690% | 86.288% | 5 | 2.581% |
| SFO | JJA | 11 | 1 | 301 | 153 | 50.831% | 56.432% | 172 | 10 | 232 | 77.076% | 81.466% | 17 | 1.260% |
| SFO | JJA | 12 | 0 | 155 | 92 | 59.355% | 66.770% | 58 | 34 | 92 | 59.355% | 66.770% | 12 | 2.418% |
| SFO | JJA | 12 | 1 | 291 | 66 | 22.680% | 27.830% | 82 | 9 | 150 | 51.546% | 57.231% | 42 | 1.303% |
| SFO | JJA | 13 | 0 | 161 | 62 | 38.509% | 46.210% | 23 | 39 | 62 | 38.509% | 46.210% | 16 | 2.330% |
| SFO | JJA | 13 | 1 | 285 | 18 | 6.316% | 9.762% | 22 | 5 | 93 | 32.632% | 38.275% | 67 | 1.330% |
| SFO | JJA | 14 | 0 | 164 | 49 | 29.878% | 37.279% | 8 | 41 | 49 | 29.878% | 37.279% | 19 | 2.289% |
| SFO | JJA | 14 | 1 | 282 | 5 | 1.773% | 4.083% | 2 | 4 | 66 | 23.404% | 28.683% | 75 | 1.344% |
| SFO | JJA | 15 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 15 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 16 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 16 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 17 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 17 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 18 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 18 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 19 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 19 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 20 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 20 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 21 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 21 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 22 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 22 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | JJA | 23 | 0 | 163 | 43 | 26.380% | 33.633% | 0 | 43 | 43 | 26.380% | 33.633% | 19 | 2.302% |
| SFO | JJA | 23 | 1 | 283 | 3 | 1.060% | 3.070% | 0 | 3 | 61 | 21.555% | 26.710% | 76 | 1.339% |
| SFO | MAM | 00 | 0 | 117 | 116 | 99.145% | 99.849% | 116 | 0 | 116 | 99.145% | 99.849% | 1 | 3.179% |
| SFO | MAM | 00 | 1 | 335 | 333 | 99.403% | 99.836% | 332 | 1 | 334 | 99.701% | 99.947% | 0 | 1.134% |
| SFO | MAM | 01 | 0 | 115 | 114 | 99.130% | 99.846% | 114 | 0 | 114 | 99.130% | 99.846% | 1 | 3.232% |
| SFO | MAM | 01 | 1 | 337 | 334 | 99.110% | 99.697% | 333 | 1 | 336 | 99.703% | 99.948% | 0 | 1.127% |
| SFO | MAM | 02 | 0 | 116 | 115 | 99.138% | 99.848% | 115 | 0 | 115 | 99.138% | 99.848% | 1 | 3.205% |
| SFO | MAM | 02 | 1 | 336 | 333 | 99.107% | 99.696% | 332 | 1 | 335 | 99.702% | 99.947% | 0 | 1.130% |
| SFO | MAM | 03 | 0 | 119 | 118 | 99.160% | 99.852% | 118 | 0 | 118 | 99.160% | 99.852% | 1 | 3.127% |
| SFO | MAM | 03 | 1 | 333 | 330 | 99.099% | 99.693% | 329 | 1 | 332 | 99.700% | 99.947% | 0 | 1.140% |
| SFO | MAM | 04 | 0 | 119 | 118 | 99.160% | 99.852% | 118 | 0 | 118 | 99.160% | 99.852% | 1 | 3.127% |
| SFO | MAM | 04 | 1 | 333 | 329 | 98.799% | 99.532% | 328 | 2 | 332 | 99.700% | 99.947% | 0 | 1.140% |
| SFO | MAM | 05 | 0 | 117 | 116 | 99.145% | 99.849% | 116 | 0 | 116 | 99.145% | 99.849% | 1 | 3.179% |
| SFO | MAM | 05 | 1 | 335 | 331 | 98.806% | 99.535% | 330 | 2 | 334 | 99.701% | 99.947% | 0 | 1.134% |
| SFO | MAM | 06 | 0 | 151 | 149 | 98.675% | 99.636% | 149 | 0 | 149 | 98.675% | 99.636% | 1 | 2.481% |
| SFO | MAM | 06 | 1 | 301 | 298 | 99.003% | 99.660% | 297 | 2 | 300 | 99.668% | 99.941% | 0 | 1.260% |
| SFO | MAM | 07 | 0 | 193 | 191 | 98.964% | 99.715% | 190 | 1 | 191 | 98.964% | 99.715% | 1 | 1.952% |
| SFO | MAM | 07 | 1 | 259 | 256 | 98.842% | 99.605% | 256 | 1 | 258 | 99.614% | 99.932% | 0 | 1.462% |
| SFO | MAM | 08 | 0 | 257 | 255 | 99.222% | 99.786% | 254 | 1 | 255 | 99.222% | 99.786% | 1 | 1.473% |
| SFO | MAM | 08 | 1 | 195 | 191 | 97.949% | 99.199% | 192 | 1 | 194 | 99.487% | 99.909% | 0 | 1.932% |
| SFO | MAM | 09 | 0 | 267 | 259 | 97.004% | 98.474% | 257 | 2 | 259 | 97.004% | 98.474% | 3 | 1.418% |
| SFO | MAM | 09 | 1 | 185 | 175 | 94.595% | 97.038% | 172 | 3 | 180 | 97.297% | 98.840% | 2 | 2.034% |
| SFO | MAM | 10 | 0 | 270 | 243 | 90.000% | 93.036% | 237 | 6 | 243 | 90.000% | 93.036% | 6 | 1.403% |
| SFO | MAM | 10 | 1 | 182 | 143 | 78.571% | 83.910% | 139 | 7 | 165 | 90.659% | 94.086% | 4 | 2.067% |
| SFO | MAM | 11 | 0 | 262 | 199 | 75.954% | 80.730% | 179 | 20 | 199 | 75.954% | 80.730% | 12 | 1.445% |
| SFO | MAM | 11 | 1 | 190 | 101 | 53.158% | 60.120% | 95 | 6 | 148 | 77.895% | 83.210% | 10 | 1.982% |
| SFO | MAM | 12 | 0 | 254 | 123 | 48.425% | 54.549% | 94 | 29 | 123 | 48.425% | 54.549% | 37 | 1.490% |
| SFO | MAM | 12 | 1 | 198 | 52 | 26.263% | 32.802% | 47 | 9 | 118 | 59.596% | 66.185% | 11 | 1.903% |
| SFO | MAM | 13 | 0 | 256 | 93 | 36.328% | 42.381% | 55 | 38 | 93 | 36.328% | 42.381% | 48 | 1.478% |
| SFO | MAM | 13 | 1 | 196 | 14 | 7.143% | 11.631% | 12 | 3 | 76 | 38.776% | 45.750% | 19 | 1.922% |
| SFO | MAM | 14 | 0 | 244 | 58 | 23.770% | 29.492% | 16 | 42 | 58 | 23.770% | 29.492% | 53 | 1.550% |
| SFO | MAM | 14 | 1 | 208 | 5 | 2.404% | 5.503% | 3 | 3 | 65 | 31.250% | 37.841% | 23 | 1.813% |
| SFO | MAM | 15 | 0 | 240 | 46 | 19.167% | 24.617% | 4 | 42 | 46 | 19.167% | 24.617% | 55 | 1.575% |
| SFO | MAM | 15 | 1 | 212 | 4 | 1.887% | 4.750% | 1 | 3 | 62 | 29.245% | 35.694% | 25 | 1.780% |
| SFO | MAM | 16 | 0 | 239 | 42 | 17.573% | 22.900% | 0 | 42 | 42 | 17.573% | 22.900% | 57 | 1.582% |
| SFO | MAM | 16 | 1 | 213 | 4 | 1.878% | 4.728% | 1 | 3 | 62 | 29.108% | 35.536% | 25 | 1.772% |
| SFO | MAM | 17 | 0 | 240 | 43 | 17.917% | 23.262% | 1 | 42 | 43 | 17.917% | 23.262% | 57 | 1.575% |
| SFO | MAM | 17 | 1 | 212 | 3 | 1.415% | 4.077% | 0 | 3 | 61 | 28.774% | 35.203% | 25 | 1.780% |
| SFO | MAM | 18 | 0 | 239 | 42 | 17.573% | 22.900% | 0 | 42 | 42 | 17.573% | 22.900% | 57 | 1.582% |
| SFO | MAM | 18 | 1 | 213 | 4 | 1.878% | 4.728% | 1 | 3 | 62 | 29.108% | 35.536% | 25 | 1.772% |
| SFO | MAM | 19 | 0 | 239 | 42 | 17.573% | 22.900% | 0 | 42 | 42 | 17.573% | 22.900% | 57 | 1.582% |
| SFO | MAM | 19 | 1 | 213 | 4 | 1.878% | 4.728% | 1 | 3 | 62 | 29.108% | 35.536% | 25 | 1.772% |
| SFO | MAM | 20 | 0 | 240 | 43 | 17.917% | 23.262% | 1 | 42 | 43 | 17.917% | 23.262% | 57 | 1.575% |
| SFO | MAM | 20 | 1 | 212 | 3 | 1.415% | 4.077% | 0 | 3 | 61 | 28.774% | 35.203% | 25 | 1.780% |
| SFO | MAM | 21 | 0 | 240 | 43 | 17.917% | 23.262% | 1 | 42 | 43 | 17.917% | 23.262% | 57 | 1.575% |
| SFO | MAM | 21 | 1 | 212 | 3 | 1.415% | 4.077% | 0 | 3 | 61 | 28.774% | 35.203% | 25 | 1.780% |
| SFO | MAM | 22 | 0 | 240 | 43 | 17.917% | 23.262% | 1 | 42 | 43 | 17.917% | 23.262% | 57 | 1.575% |
| SFO | MAM | 22 | 1 | 212 | 3 | 1.415% | 4.077% | 0 | 3 | 61 | 28.774% | 35.203% | 25 | 1.780% |
| SFO | MAM | 23 | 0 | 239 | 42 | 17.573% | 22.900% | 0 | 42 | 42 | 17.573% | 22.900% | 57 | 1.582% |
| SFO | MAM | 23 | 1 | 213 | 3 | 1.408% | 4.058% | 0 | 3 | 61 | 28.638% | 35.046% | 25 | 1.772% |
| SFO | SON | 00 | 0 | 270 | 266 | 98.519% | 99.422% | 266 | 0 | 266 | 98.519% | 99.422% | 0 | 1.403% |
| SFO | SON | 00 | 1 | 180 | 176 | 97.778% | 99.133% | 175 | 1 | 180 | 100.000% | 100.000% | 0 | 2.090% |
| SFO | SON | 01 | 0 | 272 | 268 | 98.529% | 99.427% | 268 | 0 | 268 | 98.529% | 99.427% | 0 | 1.393% |
| SFO | SON | 01 | 1 | 178 | 174 | 97.753% | 99.123% | 173 | 1 | 178 | 100.000% | 100.000% | 0 | 2.113% |
| SFO | SON | 02 | 0 | 270 | 266 | 98.519% | 99.422% | 266 | 0 | 266 | 98.519% | 99.422% | 0 | 1.403% |
| SFO | SON | 02 | 1 | 180 | 176 | 97.778% | 99.133% | 175 | 1 | 180 | 100.000% | 100.000% | 0 | 2.090% |
| SFO | SON | 03 | 0 | 274 | 270 | 98.540% | 99.431% | 270 | 0 | 270 | 98.540% | 99.431% | 0 | 1.383% |
| SFO | SON | 03 | 1 | 176 | 172 | 97.727% | 99.113% | 171 | 1 | 176 | 100.000% | 100.000% | 0 | 2.136% |
| SFO | SON | 04 | 0 | 269 | 265 | 98.513% | 99.420% | 265 | 0 | 265 | 98.513% | 99.420% | 0 | 1.408% |
| SFO | SON | 04 | 1 | 181 | 177 | 97.790% | 99.137% | 176 | 1 | 181 | 100.000% | 100.000% | 0 | 2.078% |
| SFO | SON | 05 | 0 | 271 | 267 | 98.524% | 99.425% | 267 | 0 | 267 | 98.524% | 99.425% | 0 | 1.398% |
| SFO | SON | 05 | 1 | 179 | 175 | 97.765% | 99.128% | 174 | 1 | 179 | 100.000% | 100.000% | 0 | 2.101% |
| SFO | SON | 06 | 0 | 274 | 269 | 98.175% | 99.218% | 269 | 0 | 269 | 98.175% | 99.218% | 1 | 1.383% |
| SFO | SON | 06 | 1 | 176 | 172 | 97.727% | 99.113% | 171 | 1 | 176 | 100.000% | 100.000% | 0 | 2.136% |
| SFO | SON | 07 | 0 | 276 | 271 | 98.188% | 99.224% | 271 | 0 | 271 | 98.188% | 99.224% | 1 | 1.373% |
| SFO | SON | 07 | 1 | 174 | 170 | 97.701% | 99.102% | 169 | 1 | 174 | 100.000% | 100.000% | 0 | 2.160% |
| SFO | SON | 08 | 0 | 260 | 253 | 97.308% | 98.690% | 253 | 0 | 253 | 97.308% | 98.690% | 1 | 1.456% |
| SFO | SON | 08 | 1 | 190 | 186 | 97.895% | 99.178% | 186 | 1 | 190 | 100.000% | 100.000% | 0 | 1.982% |
| SFO | SON | 09 | 0 | 238 | 230 | 96.639% | 98.287% | 230 | 0 | 230 | 96.639% | 98.287% | 1 | 1.588% |
| SFO | SON | 09 | 1 | 212 | 200 | 94.340% | 96.733% | 199 | 3 | 209 | 98.585% | 99.518% | 0 | 1.780% |
| SFO | SON | 10 | 0 | 218 | 201 | 92.202% | 95.074% | 199 | 2 | 201 | 92.202% | 95.074% | 1 | 1.732% |
| SFO | SON | 10 | 1 | 232 | 201 | 86.638% | 90.424% | 205 | 5 | 222 | 95.690% | 97.642% | 0 | 1.629% |
| SFO | SON | 11 | 0 | 206 | 169 | 82.039% | 86.679% | 161 | 8 | 169 | 82.039% | 86.679% | 6 | 1.831% |
| SFO | SON | 11 | 1 | 244 | 157 | 64.344% | 70.089% | 159 | 9 | 207 | 84.836% | 88.794% | 7 | 1.550% |
| SFO | SON | 12 | 0 | 207 | 141 | 68.116% | 74.085% | 119 | 22 | 141 | 68.116% | 74.085% | 8 | 1.822% |
| SFO | SON | 12 | 1 | 243 | 103 | 42.387% | 48.671% | 101 | 9 | 159 | 65.432% | 71.130% | 16 | 1.556% |
| SFO | SON | 13 | 0 | 217 | 105 | 48.387% | 55.006% | 70 | 35 | 105 | 48.387% | 55.006% | 16 | 1.739% |
| SFO | SON | 13 | 1 | 233 | 46 | 19.742% | 25.326% | 43 | 5 | 104 | 44.635% | 51.054% | 26 | 1.622% |
| SFO | SON | 14 | 0 | 214 | 77 | 35.981% | 42.607% | 33 | 44 | 77 | 35.981% | 42.607% | 22 | 1.763% |
| SFO | SON | 14 | 1 | 236 | 10 | 4.237% | 7.623% | 11 | 0 | 66 | 27.966% | 34.010% | 31 | 1.602% |
| SFO | SON | 15 | 0 | 199 | 52 | 26.131% | 32.646% | 5 | 47 | 52 | 26.131% | 32.646% | 25 | 1.894% |
| SFO | SON | 15 | 1 | 251 | 3 | 1.195% | 3.454% | 3 | 0 | 61 | 24.303% | 29.970% | 34 | 1.507% |
| SFO | SON | 16 | 0 | 198 | 48 | 24.242% | 30.665% | 1 | 47 | 48 | 24.242% | 30.665% | 26 | 1.903% |
| SFO | SON | 16 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 17 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 17 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 18 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 18 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 19 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 19 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 20 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 20 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 21 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 21 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 22 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 22 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |
| SFO | SON | 23 | 0 | 198 | 47 | 23.737% | 30.128% | 0 | 47 | 47 | 23.737% | 30.128% | 26 | 1.903% |
| SFO | SON | 23 | 1 | 252 | 0 | 0.000% | 1.501% | 0 | 0 | 58 | 23.016% | 28.595% | 35 | 1.501% |

### 7.2 basis `obs`

| station | season | hour | headroom | n | cross | cross rate | cross Wilson-95 UPPER | of which physics | of which basis-only | exceed | exceed rate | exceed Wilson-95 UPPER | neg-basis | resolution floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LAX | DJF | 00 | 0 | 253 | 246 | 97.233% | 98.653% | 246 | 0 | 246 | 97.233% | 98.653% | 0 | 1.496% |
| LAX | DJF | 00 | 1 | 195 | 188 | 96.410% | 98.250% | 188 | 0 | 190 | 97.436% | 98.900% | 0 | 1.932% |
| LAX | DJF | 01 | 0 | 259 | 252 | 97.297% | 98.685% | 252 | 0 | 252 | 97.297% | 98.685% | 0 | 1.462% |
| LAX | DJF | 01 | 1 | 189 | 182 | 96.296% | 98.195% | 182 | 0 | 184 | 97.354% | 98.865% | 0 | 1.992% |
| LAX | DJF | 02 | 0 | 256 | 249 | 97.266% | 98.669% | 249 | 0 | 249 | 97.266% | 98.669% | 0 | 1.478% |
| LAX | DJF | 02 | 1 | 192 | 184 | 95.833% | 97.874% | 184 | 0 | 187 | 97.396% | 98.883% | 0 | 1.962% |
| LAX | DJF | 03 | 0 | 254 | 247 | 97.244% | 98.659% | 247 | 0 | 247 | 97.244% | 98.659% | 0 | 1.490% |
| LAX | DJF | 03 | 1 | 194 | 185 | 95.361% | 97.540% | 185 | 0 | 188 | 96.907% | 98.575% | 0 | 1.942% |
| LAX | DJF | 04 | 0 | 252 | 245 | 97.222% | 98.648% | 245 | 0 | 245 | 97.222% | 98.648% | 0 | 1.501% |
| LAX | DJF | 04 | 1 | 196 | 187 | 95.408% | 97.566% | 187 | 0 | 190 | 96.939% | 98.590% | 0 | 1.922% |
| LAX | DJF | 05 | 0 | 249 | 242 | 97.189% | 98.632% | 242 | 0 | 242 | 97.189% | 98.632% | 0 | 1.519% |
| LAX | DJF | 05 | 1 | 199 | 190 | 95.477% | 97.603% | 190 | 0 | 193 | 96.985% | 98.611% | 0 | 1.894% |
| LAX | DJF | 06 | 0 | 250 | 243 | 97.200% | 98.637% | 243 | 0 | 243 | 97.200% | 98.637% | 0 | 1.513% |
| LAX | DJF | 06 | 1 | 198 | 189 | 95.455% | 97.590% | 189 | 0 | 192 | 96.970% | 98.604% | 0 | 1.903% |
| LAX | DJF | 07 | 0 | 247 | 239 | 96.761% | 98.350% | 239 | 0 | 239 | 96.761% | 98.350% | 0 | 1.531% |
| LAX | DJF | 07 | 1 | 201 | 191 | 95.025% | 97.275% | 191 | 0 | 194 | 96.517% | 98.303% | 0 | 1.875% |
| LAX | DJF | 08 | 0 | 263 | 253 | 96.198% | 97.922% | 253 | 0 | 253 | 96.198% | 97.922% | 0 | 1.440% |
| LAX | DJF | 08 | 1 | 185 | 176 | 95.135% | 97.420% | 176 | 0 | 178 | 96.216% | 98.155% | 0 | 2.034% |
| LAX | DJF | 09 | 0 | 290 | 274 | 94.483% | 96.576% | 274 | 0 | 274 | 94.483% | 96.576% | 0 | 1.307% |
| LAX | DJF | 09 | 1 | 158 | 143 | 90.506% | 94.162% | 143 | 0 | 148 | 93.671% | 96.526% | 0 | 2.374% |
| LAX | DJF | 10 | 0 | 275 | 218 | 79.273% | 83.644% | 218 | 0 | 218 | 79.273% | 83.644% | 0 | 1.378% |
| LAX | DJF | 10 | 1 | 173 | 114 | 65.896% | 72.546% | 114 | 0 | 134 | 77.457% | 83.048% | 0 | 2.172% |
| LAX | DJF | 11 | 0 | 250 | 117 | 46.800% | 52.987% | 117 | 0 | 117 | 46.800% | 52.987% | 0 | 1.513% |
| LAX | DJF | 11 | 1 | 198 | 66 | 33.333% | 40.162% | 66 | 0 | 97 | 48.990% | 55.906% | 0 | 1.903% |
| LAX | DJF | 12 | 0 | 237 | 49 | 20.675% | 26.279% | 49 | 0 | 49 | 20.675% | 26.279% | 0 | 1.595% |
| LAX | DJF | 12 | 1 | 211 | 34 | 16.114% | 21.673% | 34 | 0 | 60 | 28.436% | 34.866% | 0 | 1.788% |
| LAX | DJF | 13 | 0 | 246 | 27 | 10.976% | 15.498% | 27 | 0 | 27 | 10.976% | 15.498% | 0 | 1.538% |
| LAX | DJF | 13 | 1 | 202 | 15 | 7.426% | 11.889% | 15 | 0 | 22 | 10.891% | 15.939% | 0 | 1.866% |
| LAX | DJF | 14 | 0 | 244 | 9 | 3.689% | 6.860% | 9 | 0 | 9 | 3.689% | 6.860% | 0 | 1.550% |
| LAX | DJF | 14 | 1 | 204 | 8 | 3.922% | 7.546% | 8 | 0 | 10 | 4.902% | 8.787% | 0 | 1.848% |
| LAX | DJF | 15 | 0 | 245 | 5 | 2.041% | 4.688% | 5 | 0 | 5 | 2.041% | 4.688% | 0 | 1.544% |
| LAX | DJF | 15 | 1 | 203 | 5 | 2.463% | 5.635% | 5 | 0 | 7 | 3.448% | 6.945% | 0 | 1.857% |
| LAX | DJF | 16 | 0 | 246 | 4 | 1.626% | 4.105% | 4 | 0 | 4 | 1.626% | 4.105% | 0 | 1.538% |
| LAX | DJF | 16 | 1 | 202 | 4 | 1.980% | 4.980% | 4 | 0 | 5 | 2.475% | 5.663% | 0 | 1.866% |
| LAX | DJF | 17 | 0 | 246 | 3 | 1.220% | 3.523% | 3 | 0 | 3 | 1.220% | 3.523% | 0 | 1.538% |
| LAX | DJF | 17 | 1 | 202 | 5 | 2.475% | 5.663% | 5 | 0 | 5 | 2.475% | 5.663% | 0 | 1.866% |
| LAX | DJF | 18 | 0 | 247 | 4 | 1.619% | 4.089% | 4 | 0 | 4 | 1.619% | 4.089% | 0 | 1.531% |
| LAX | DJF | 18 | 1 | 201 | 3 | 1.493% | 4.296% | 3 | 0 | 4 | 1.990% | 5.004% | 0 | 1.875% |
| LAX | DJF | 19 | 0 | 250 | 4 | 1.600% | 4.041% | 4 | 0 | 4 | 1.600% | 4.041% | 0 | 1.513% |
| LAX | DJF | 19 | 1 | 198 | 1 | 0.505% | 2.805% | 1 | 0 | 1 | 0.505% | 2.805% | 0 | 1.903% |
| LAX | DJF | 20 | 0 | 249 | 3 | 1.205% | 3.482% | 3 | 0 | 3 | 1.205% | 3.482% | 0 | 1.519% |
| LAX | DJF | 20 | 1 | 199 | 0 | 0.000% | 1.894% | 0 | 0 | 0 | 0.000% | 1.894% | 0 | 1.894% |
| LAX | DJF | 21 | 0 | 248 | 2 | 0.806% | 2.892% | 2 | 0 | 2 | 0.806% | 2.892% | 0 | 1.525% |
| LAX | DJF | 21 | 1 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| LAX | DJF | 22 | 0 | 247 | 1 | 0.405% | 2.257% | 1 | 0 | 1 | 0.405% | 2.257% | 0 | 1.531% |
| LAX | DJF | 22 | 1 | 201 | 0 | 0.000% | 1.875% | 0 | 0 | 0 | 0.000% | 1.875% | 0 | 1.875% |
| LAX | DJF | 23 | 0 | 247 | 0 | 0.000% | 1.531% | 0 | 0 | 0 | 0.000% | 1.531% | 0 | 1.531% |
| LAX | DJF | 23 | 1 | 201 | 0 | 0.000% | 1.875% | 0 | 0 | 0 | 0.000% | 1.875% | 0 | 1.875% |
| LAX | JJA | 00 | 0 | 207 | 207 | 100.000% | 100.000% | 207 | 0 | 207 | 100.000% | 100.000% | 0 | 1.822% |
| LAX | JJA | 00 | 1 | 251 | 251 | 100.000% | 100.000% | 251 | 0 | 251 | 100.000% | 100.000% | 0 | 1.507% |
| LAX | JJA | 01 | 0 | 201 | 201 | 100.000% | 100.000% | 201 | 0 | 201 | 100.000% | 100.000% | 0 | 1.875% |
| LAX | JJA | 01 | 1 | 257 | 257 | 100.000% | 100.000% | 257 | 0 | 257 | 100.000% | 100.000% | 0 | 1.473% |
| LAX | JJA | 02 | 0 | 199 | 199 | 100.000% | 100.000% | 199 | 0 | 199 | 100.000% | 100.000% | 0 | 1.894% |
| LAX | JJA | 02 | 1 | 259 | 259 | 100.000% | 100.000% | 259 | 0 | 259 | 100.000% | 100.000% | 0 | 1.462% |
| LAX | JJA | 03 | 0 | 207 | 207 | 100.000% | 100.000% | 207 | 0 | 207 | 100.000% | 100.000% | 0 | 1.822% |
| LAX | JJA | 03 | 1 | 251 | 251 | 100.000% | 100.000% | 251 | 0 | 251 | 100.000% | 100.000% | 0 | 1.507% |
| LAX | JJA | 04 | 0 | 208 | 208 | 100.000% | 100.000% | 208 | 0 | 208 | 100.000% | 100.000% | 0 | 1.813% |
| LAX | JJA | 04 | 1 | 250 | 249 | 99.600% | 99.929% | 249 | 0 | 250 | 100.000% | 100.000% | 0 | 1.513% |
| LAX | JJA | 05 | 0 | 208 | 207 | 99.519% | 99.915% | 207 | 0 | 207 | 99.519% | 99.915% | 0 | 1.813% |
| LAX | JJA | 05 | 1 | 250 | 250 | 100.000% | 100.000% | 250 | 0 | 250 | 100.000% | 100.000% | 0 | 1.513% |
| LAX | JJA | 06 | 0 | 186 | 185 | 99.462% | 99.905% | 185 | 0 | 185 | 99.462% | 99.905% | 0 | 2.024% |
| LAX | JJA | 06 | 1 | 272 | 272 | 100.000% | 100.000% | 272 | 0 | 272 | 100.000% | 100.000% | 0 | 1.393% |
| LAX | JJA | 07 | 0 | 152 | 151 | 99.342% | 99.884% | 151 | 0 | 151 | 99.342% | 99.884% | 0 | 2.465% |
| LAX | JJA | 07 | 1 | 306 | 299 | 97.712% | 98.888% | 299 | 0 | 305 | 99.673% | 99.942% | 0 | 1.240% |
| LAX | JJA | 08 | 0 | 170 | 145 | 85.294% | 89.836% | 145 | 0 | 145 | 85.294% | 89.836% | 0 | 2.210% |
| LAX | JJA | 08 | 1 | 288 | 245 | 85.069% | 88.723% | 245 | 0 | 273 | 94.792% | 96.819% | 0 | 1.316% |
| LAX | JJA | 09 | 0 | 193 | 125 | 64.767% | 71.158% | 125 | 0 | 125 | 64.767% | 71.158% | 0 | 1.952% |
| LAX | JJA | 09 | 1 | 265 | 163 | 61.509% | 67.164% | 163 | 0 | 210 | 79.245% | 83.693% | 0 | 1.429% |
| LAX | JJA | 10 | 0 | 199 | 85 | 42.714% | 49.660% | 85 | 0 | 85 | 42.714% | 49.660% | 0 | 1.894% |
| LAX | JJA | 10 | 1 | 259 | 101 | 38.996% | 45.056% | 101 | 0 | 157 | 60.618% | 66.371% | 0 | 1.462% |
| LAX | JJA | 11 | 0 | 224 | 60 | 26.786% | 32.941% | 60 | 0 | 60 | 26.786% | 32.941% | 0 | 1.686% |
| LAX | JJA | 11 | 1 | 234 | 45 | 19.231% | 24.761% | 45 | 0 | 86 | 36.752% | 43.097% | 0 | 1.615% |
| LAX | JJA | 12 | 0 | 232 | 26 | 11.207% | 15.914% | 26 | 0 | 26 | 11.207% | 15.914% | 0 | 1.629% |
| LAX | JJA | 12 | 1 | 226 | 19 | 8.407% | 12.756% | 19 | 0 | 40 | 17.699% | 23.203% | 0 | 1.671% |
| LAX | JJA | 13 | 0 | 235 | 5 | 2.128% | 4.883% | 5 | 0 | 5 | 2.128% | 4.883% | 0 | 1.608% |
| LAX | JJA | 13 | 1 | 223 | 9 | 4.036% | 7.491% | 9 | 0 | 18 | 8.072% | 12.397% | 0 | 1.693% |
| LAX | JJA | 14 | 0 | 237 | 0 | 0.000% | 1.595% | 0 | 0 | 0 | 0.000% | 1.595% | 0 | 1.595% |
| LAX | JJA | 14 | 1 | 221 | 1 | 0.452% | 2.518% | 1 | 0 | 4 | 1.810% | 4.561% | 0 | 1.709% |
| LAX | JJA | 15 | 0 | 239 | 0 | 0.000% | 1.582% | 0 | 0 | 0 | 0.000% | 1.582% | 0 | 1.582% |
| LAX | JJA | 15 | 1 | 219 | 1 | 0.457% | 2.541% | 1 | 0 | 2 | 0.913% | 3.268% | 0 | 1.724% |
| LAX | JJA | 16 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 16 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 17 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 17 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 18 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 18 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 19 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 19 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 20 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 20 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 21 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 21 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 22 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 22 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | JJA | 23 | 0 | 240 | 0 | 0.000% | 1.575% | 0 | 0 | 0 | 0.000% | 1.575% | 0 | 1.575% |
| LAX | JJA | 23 | 1 | 218 | 0 | 0.000% | 1.732% | 0 | 0 | 0 | 0.000% | 1.732% | 0 | 1.732% |
| LAX | MAM | 00 | 0 | 301 | 300 | 99.668% | 99.941% | 300 | 0 | 300 | 99.668% | 99.941% | 0 | 1.260% |
| LAX | MAM | 00 | 1 | 159 | 157 | 98.742% | 99.654% | 157 | 0 | 159 | 100.000% | 100.000% | 0 | 2.359% |
| LAX | MAM | 01 | 0 | 299 | 298 | 99.666% | 99.941% | 298 | 0 | 298 | 99.666% | 99.941% | 0 | 1.268% |
| LAX | MAM | 01 | 1 | 161 | 158 | 98.137% | 99.364% | 158 | 0 | 160 | 99.379% | 99.890% | 0 | 2.330% |
| LAX | MAM | 02 | 0 | 297 | 296 | 99.663% | 99.941% | 296 | 0 | 296 | 99.663% | 99.941% | 0 | 1.277% |
| LAX | MAM | 02 | 1 | 163 | 159 | 97.546% | 99.042% | 159 | 0 | 162 | 99.387% | 99.892% | 0 | 2.302% |
| LAX | MAM | 03 | 0 | 297 | 295 | 99.327% | 99.815% | 295 | 0 | 295 | 99.327% | 99.815% | 0 | 1.277% |
| LAX | MAM | 03 | 1 | 163 | 159 | 97.546% | 99.042% | 159 | 0 | 162 | 99.387% | 99.892% | 0 | 2.302% |
| LAX | MAM | 04 | 0 | 301 | 298 | 99.003% | 99.660% | 298 | 0 | 298 | 99.003% | 99.660% | 0 | 1.260% |
| LAX | MAM | 04 | 1 | 159 | 156 | 98.113% | 99.356% | 156 | 0 | 158 | 99.371% | 99.889% | 0 | 2.359% |
| LAX | MAM | 05 | 0 | 300 | 296 | 98.667% | 99.480% | 296 | 0 | 296 | 98.667% | 99.480% | 0 | 1.264% |
| LAX | MAM | 05 | 1 | 160 | 157 | 98.125% | 99.360% | 157 | 0 | 159 | 99.375% | 99.890% | 0 | 2.345% |
| LAX | MAM | 06 | 0 | 296 | 292 | 98.649% | 99.473% | 292 | 0 | 292 | 98.649% | 99.473% | 0 | 1.281% |
| LAX | MAM | 06 | 1 | 164 | 161 | 98.171% | 99.376% | 161 | 0 | 163 | 99.390% | 99.892% | 0 | 2.289% |
| LAX | MAM | 07 | 0 | 321 | 317 | 98.754% | 99.514% | 317 | 0 | 317 | 98.754% | 99.514% | 0 | 1.183% |
| LAX | MAM | 07 | 1 | 139 | 135 | 97.122% | 98.875% | 135 | 0 | 138 | 99.281% | 99.873% | 0 | 2.689% |
| LAX | MAM | 08 | 0 | 296 | 286 | 96.622% | 98.155% | 286 | 0 | 286 | 96.622% | 98.155% | 0 | 1.281% |
| LAX | MAM | 08 | 1 | 164 | 145 | 88.415% | 92.456% | 145 | 0 | 154 | 93.902% | 96.655% | 0 | 2.289% |
| LAX | MAM | 09 | 0 | 272 | 234 | 86.029% | 89.649% | 234 | 0 | 234 | 86.029% | 89.649% | 0 | 1.393% |
| LAX | MAM | 09 | 1 | 188 | 123 | 65.426% | 71.854% | 123 | 0 | 143 | 76.064% | 81.602% | 0 | 2.002% |
| LAX | MAM | 10 | 0 | 260 | 170 | 65.385% | 70.905% | 170 | 0 | 170 | 65.385% | 70.905% | 0 | 1.456% |
| LAX | MAM | 10 | 1 | 200 | 75 | 37.500% | 44.386% | 75 | 0 | 97 | 48.500% | 55.389% | 0 | 1.885% |
| LAX | MAM | 11 | 0 | 226 | 80 | 35.398% | 41.829% | 80 | 0 | 80 | 35.398% | 41.829% | 0 | 1.671% |
| LAX | MAM | 11 | 1 | 234 | 39 | 16.667% | 21.972% | 39 | 0 | 64 | 27.350% | 33.393% | 0 | 1.615% |
| LAX | MAM | 12 | 0 | 217 | 37 | 17.051% | 22.617% | 37 | 0 | 37 | 17.051% | 22.617% | 0 | 1.739% |
| LAX | MAM | 12 | 1 | 243 | 14 | 5.761% | 9.437% | 14 | 0 | 26 | 10.700% | 15.216% | 0 | 1.556% |
| LAX | MAM | 13 | 0 | 214 | 10 | 4.673% | 8.387% | 10 | 0 | 10 | 4.673% | 8.387% | 0 | 1.763% |
| LAX | MAM | 13 | 1 | 246 | 3 | 1.220% | 3.523% | 3 | 0 | 5 | 2.033% | 4.669% | 0 | 1.538% |
| LAX | MAM | 14 | 0 | 212 | 5 | 2.358% | 5.401% | 5 | 0 | 5 | 2.358% | 5.401% | 0 | 1.780% |
| LAX | MAM | 14 | 1 | 248 | 2 | 0.806% | 2.892% | 2 | 0 | 3 | 1.210% | 3.496% | 0 | 1.525% |
| LAX | MAM | 15 | 0 | 212 | 3 | 1.415% | 4.077% | 3 | 0 | 3 | 1.415% | 4.077% | 0 | 1.780% |
| LAX | MAM | 15 | 1 | 248 | 1 | 0.403% | 2.248% | 1 | 0 | 2 | 0.806% | 2.892% | 0 | 1.525% |
| LAX | MAM | 16 | 0 | 212 | 3 | 1.415% | 4.077% | 3 | 0 | 3 | 1.415% | 4.077% | 0 | 1.780% |
| LAX | MAM | 16 | 1 | 248 | 1 | 0.403% | 2.248% | 1 | 0 | 2 | 0.806% | 2.892% | 0 | 1.525% |
| LAX | MAM | 17 | 0 | 212 | 2 | 0.943% | 3.374% | 2 | 0 | 2 | 0.943% | 3.374% | 0 | 1.780% |
| LAX | MAM | 17 | 1 | 248 | 1 | 0.403% | 2.248% | 1 | 0 | 1 | 0.403% | 2.248% | 0 | 1.525% |
| LAX | MAM | 18 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 18 | 1 | 250 | 1 | 0.400% | 2.231% | 1 | 0 | 1 | 0.400% | 2.231% | 0 | 1.513% |
| LAX | MAM | 19 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 19 | 1 | 250 | 1 | 0.400% | 2.231% | 1 | 0 | 1 | 0.400% | 2.231% | 0 | 1.513% |
| LAX | MAM | 20 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 20 | 1 | 250 | 1 | 0.400% | 2.231% | 1 | 0 | 1 | 0.400% | 2.231% | 0 | 1.513% |
| LAX | MAM | 21 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 21 | 1 | 250 | 0 | 0.000% | 1.513% | 0 | 0 | 0 | 0.000% | 1.513% | 0 | 1.513% |
| LAX | MAM | 22 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 22 | 1 | 250 | 0 | 0.000% | 1.513% | 0 | 0 | 0 | 0.000% | 1.513% | 0 | 1.513% |
| LAX | MAM | 23 | 0 | 210 | 0 | 0.000% | 1.796% | 0 | 0 | 0 | 0.000% | 1.796% | 0 | 1.796% |
| LAX | MAM | 23 | 1 | 250 | 0 | 0.000% | 1.513% | 0 | 0 | 0 | 0.000% | 1.513% | 0 | 1.513% |
| LAX | SON | 00 | 0 | 254 | 252 | 99.213% | 99.784% | 252 | 0 | 252 | 99.213% | 99.784% | 0 | 1.490% |
| LAX | SON | 00 | 1 | 198 | 197 | 99.495% | 99.911% | 197 | 0 | 197 | 99.495% | 99.911% | 0 | 1.903% |
| LAX | SON | 01 | 0 | 257 | 255 | 99.222% | 99.786% | 255 | 0 | 255 | 99.222% | 99.786% | 0 | 1.473% |
| LAX | SON | 01 | 1 | 195 | 194 | 99.487% | 99.909% | 194 | 0 | 194 | 99.487% | 99.909% | 0 | 1.932% |
| LAX | SON | 02 | 0 | 263 | 261 | 99.240% | 99.791% | 261 | 0 | 261 | 99.240% | 99.791% | 0 | 1.440% |
| LAX | SON | 02 | 1 | 189 | 188 | 99.471% | 99.907% | 188 | 0 | 188 | 99.471% | 99.907% | 0 | 1.992% |
| LAX | SON | 03 | 0 | 263 | 261 | 99.240% | 99.791% | 261 | 0 | 261 | 99.240% | 99.791% | 0 | 1.440% |
| LAX | SON | 03 | 1 | 189 | 188 | 99.471% | 99.907% | 188 | 0 | 188 | 99.471% | 99.907% | 0 | 1.992% |
| LAX | SON | 04 | 0 | 259 | 257 | 99.228% | 99.788% | 257 | 0 | 257 | 99.228% | 99.788% | 0 | 1.462% |
| LAX | SON | 04 | 1 | 193 | 192 | 99.482% | 99.908% | 192 | 0 | 192 | 99.482% | 99.908% | 0 | 1.952% |
| LAX | SON | 05 | 0 | 262 | 260 | 99.237% | 99.790% | 260 | 0 | 260 | 99.237% | 99.790% | 0 | 1.445% |
| LAX | SON | 05 | 1 | 190 | 189 | 99.474% | 99.907% | 189 | 0 | 189 | 99.474% | 99.907% | 0 | 1.982% |
| LAX | SON | 06 | 0 | 257 | 255 | 99.222% | 99.786% | 255 | 0 | 255 | 99.222% | 99.786% | 0 | 1.473% |
| LAX | SON | 06 | 1 | 195 | 193 | 98.974% | 99.718% | 193 | 0 | 193 | 98.974% | 99.718% | 0 | 1.932% |
| LAX | SON | 07 | 0 | 230 | 227 | 98.696% | 99.555% | 227 | 0 | 227 | 98.696% | 99.555% | 0 | 1.643% |
| LAX | SON | 07 | 1 | 222 | 220 | 99.099% | 99.753% | 220 | 0 | 220 | 99.099% | 99.753% | 0 | 1.701% |
| LAX | SON | 08 | 0 | 215 | 211 | 98.140% | 99.274% | 211 | 0 | 211 | 98.140% | 99.274% | 0 | 1.755% |
| LAX | SON | 08 | 1 | 237 | 232 | 97.890% | 99.096% | 232 | 0 | 234 | 98.734% | 99.569% | 0 | 1.595% |
| LAX | SON | 09 | 0 | 188 | 159 | 84.574% | 89.040% | 159 | 0 | 159 | 84.574% | 89.040% | 0 | 2.002% |
| LAX | SON | 09 | 1 | 264 | 201 | 76.136% | 80.880% | 201 | 0 | 225 | 85.227% | 89.001% | 0 | 1.434% |
| LAX | SON | 10 | 0 | 195 | 112 | 57.436% | 64.166% | 112 | 0 | 112 | 57.436% | 64.166% | 0 | 1.932% |
| LAX | SON | 10 | 1 | 257 | 102 | 39.689% | 45.780% | 102 | 0 | 137 | 53.307% | 59.313% | 0 | 1.473% |
| LAX | SON | 11 | 0 | 198 | 61 | 30.808% | 37.553% | 61 | 0 | 61 | 30.808% | 37.553% | 0 | 1.903% |
| LAX | SON | 11 | 1 | 254 | 51 | 20.079% | 25.434% | 51 | 0 | 74 | 29.134% | 35.000% | 0 | 1.490% |
| LAX | SON | 12 | 0 | 192 | 18 | 9.375% | 14.331% | 18 | 0 | 18 | 9.375% | 14.331% | 0 | 1.962% |
| LAX | SON | 12 | 1 | 260 | 20 | 7.692% | 11.582% | 20 | 0 | 29 | 11.154% | 15.560% | 0 | 1.456% |
| LAX | SON | 13 | 0 | 189 | 3 | 1.587% | 4.562% | 3 | 0 | 3 | 1.587% | 4.562% | 0 | 1.992% |
| LAX | SON | 13 | 1 | 263 | 9 | 3.422% | 6.375% | 9 | 0 | 12 | 4.563% | 7.805% | 0 | 1.440% |
| LAX | SON | 14 | 0 | 193 | 1 | 0.518% | 2.876% | 1 | 0 | 1 | 0.518% | 2.876% | 0 | 1.952% |
| LAX | SON | 14 | 1 | 259 | 2 | 0.772% | 2.771% | 2 | 0 | 2 | 0.772% | 2.771% | 0 | 1.462% |
| LAX | SON | 15 | 0 | 194 | 2 | 1.031% | 3.680% | 2 | 0 | 2 | 1.031% | 3.680% | 0 | 1.942% |
| LAX | SON | 15 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 16 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 16 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 17 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 17 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 18 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 18 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 19 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 19 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 20 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 20 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 21 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 21 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 22 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 22 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| LAX | SON | 23 | 0 | 194 | 0 | 0.000% | 1.942% | 0 | 0 | 0 | 0.000% | 1.942% | 0 | 1.942% |
| LAX | SON | 23 | 1 | 258 | 0 | 0.000% | 1.467% | 0 | 0 | 0 | 0.000% | 1.467% | 0 | 1.467% |
| MDW | DJF | 00 | 0 | 219 | 186 | 84.932% | 89.065% | 186 | 0 | 186 | 84.932% | 89.065% | 0 | 1.724% |
| MDW | DJF | 00 | 1 | 232 | 184 | 79.310% | 84.025% | 184 | 0 | 189 | 81.466% | 85.939% | 0 | 1.629% |
| MDW | DJF | 01 | 0 | 216 | 182 | 84.259% | 88.512% | 182 | 0 | 182 | 84.259% | 88.512% | 0 | 1.747% |
| MDW | DJF | 01 | 1 | 235 | 184 | 78.298% | 83.090% | 184 | 0 | 189 | 80.426% | 84.992% | 0 | 1.608% |
| MDW | DJF | 02 | 0 | 218 | 181 | 83.028% | 87.428% | 181 | 0 | 181 | 83.028% | 87.428% | 0 | 1.732% |
| MDW | DJF | 02 | 1 | 233 | 184 | 78.970% | 83.711% | 184 | 0 | 186 | 79.828% | 84.478% | 0 | 1.622% |
| MDW | DJF | 03 | 0 | 219 | 181 | 82.648% | 87.089% | 181 | 0 | 181 | 82.648% | 87.089% | 0 | 1.724% |
| MDW | DJF | 03 | 1 | 232 | 182 | 78.448% | 83.253% | 182 | 0 | 184 | 79.310% | 84.025% | 0 | 1.629% |
| MDW | DJF | 04 | 0 | 215 | 177 | 82.326% | 86.844% | 177 | 0 | 177 | 82.326% | 86.844% | 0 | 1.755% |
| MDW | DJF | 04 | 1 | 236 | 184 | 77.966% | 82.783% | 184 | 0 | 187 | 79.237% | 83.924% | 0 | 1.602% |
| MDW | DJF | 05 | 0 | 220 | 179 | 81.364% | 85.955% | 179 | 0 | 179 | 81.364% | 85.955% | 0 | 1.716% |
| MDW | DJF | 05 | 1 | 231 | 177 | 76.623% | 81.618% | 177 | 0 | 180 | 77.922% | 82.790% | 0 | 1.636% |
| MDW | DJF | 06 | 0 | 219 | 178 | 81.279% | 85.889% | 178 | 0 | 178 | 81.279% | 85.889% | 0 | 1.724% |
| MDW | DJF | 06 | 1 | 232 | 176 | 75.862% | 80.918% | 176 | 0 | 180 | 77.586% | 82.478% | 0 | 1.629% |
| MDW | DJF | 07 | 0 | 215 | 174 | 80.930% | 85.620% | 174 | 0 | 174 | 80.930% | 85.620% | 0 | 1.755% |
| MDW | DJF | 07 | 1 | 236 | 179 | 75.847% | 80.866% | 179 | 0 | 183 | 77.542% | 82.401% | 0 | 1.602% |
| MDW | DJF | 08 | 0 | 222 | 177 | 79.730% | 84.491% | 177 | 0 | 177 | 79.730% | 84.491% | 0 | 1.701% |
| MDW | DJF | 08 | 1 | 229 | 168 | 73.362% | 78.668% | 168 | 0 | 174 | 75.983% | 81.058% | 0 | 1.650% |
| MDW | DJF | 09 | 0 | 200 | 153 | 76.500% | 81.843% | 153 | 0 | 153 | 76.500% | 81.843% | 0 | 1.885% |
| MDW | DJF | 09 | 1 | 251 | 182 | 72.510% | 77.663% | 182 | 0 | 193 | 76.892% | 81.678% | 0 | 1.507% |
| MDW | DJF | 10 | 0 | 210 | 156 | 74.286% | 79.724% | 156 | 0 | 156 | 74.286% | 79.724% | 0 | 1.796% |
| MDW | DJF | 10 | 1 | 241 | 158 | 65.560% | 71.273% | 158 | 0 | 174 | 72.199% | 77.473% | 0 | 1.569% |
| MDW | DJF | 11 | 0 | 226 | 157 | 69.469% | 75.106% | 157 | 0 | 157 | 69.469% | 75.106% | 0 | 1.671% |
| MDW | DJF | 11 | 1 | 225 | 120 | 53.333% | 59.741% | 120 | 0 | 142 | 63.111% | 69.146% | 0 | 1.679% |
| MDW | DJF | 12 | 0 | 214 | 116 | 54.206% | 60.748% | 116 | 0 | 116 | 54.206% | 60.748% | 0 | 1.763% |
| MDW | DJF | 12 | 1 | 237 | 97 | 40.928% | 47.285% | 97 | 0 | 125 | 52.743% | 59.004% | 0 | 1.595% |
| MDW | DJF | 13 | 0 | 216 | 73 | 33.796% | 40.339% | 73 | 0 | 73 | 33.796% | 40.339% | 0 | 1.747% |
| MDW | DJF | 13 | 1 | 235 | 54 | 22.979% | 28.766% | 54 | 0 | 72 | 30.638% | 36.804% | 0 | 1.608% |
| MDW | DJF | 14 | 0 | 218 | 54 | 24.771% | 30.905% | 54 | 0 | 54 | 24.771% | 30.905% | 0 | 1.732% |
| MDW | DJF | 14 | 1 | 233 | 30 | 12.876% | 17.785% | 30 | 0 | 38 | 16.309% | 21.592% | 0 | 1.622% |
| MDW | DJF | 15 | 0 | 214 | 37 | 17.290% | 22.921% | 37 | 0 | 37 | 17.290% | 22.921% | 0 | 1.763% |
| MDW | DJF | 15 | 1 | 237 | 21 | 8.861% | 13.165% | 21 | 0 | 26 | 10.970% | 15.589% | 0 | 1.595% |
| MDW | DJF | 16 | 0 | 212 | 33 | 15.566% | 21.054% | 33 | 0 | 33 | 15.566% | 21.054% | 0 | 1.780% |
| MDW | DJF | 16 | 1 | 239 | 16 | 6.695% | 10.597% | 16 | 0 | 20 | 8.368% | 12.571% | 0 | 1.582% |
| MDW | DJF | 17 | 0 | 212 | 29 | 13.679% | 18.955% | 29 | 0 | 29 | 13.679% | 18.955% | 0 | 1.780% |
| MDW | DJF | 17 | 1 | 239 | 14 | 5.858% | 9.591% | 14 | 0 | 17 | 7.113% | 11.095% | 0 | 1.582% |
| MDW | DJF | 18 | 0 | 209 | 24 | 11.483% | 16.518% | 24 | 0 | 24 | 11.483% | 16.518% | 0 | 1.805% |
| MDW | DJF | 18 | 1 | 242 | 16 | 6.612% | 10.469% | 16 | 0 | 19 | 7.851% | 11.936% | 0 | 1.563% |
| MDW | DJF | 19 | 0 | 210 | 22 | 10.476% | 15.352% | 22 | 0 | 22 | 10.476% | 15.352% | 0 | 1.796% |
| MDW | DJF | 19 | 1 | 241 | 13 | 5.394% | 9.009% | 13 | 0 | 15 | 6.224% | 10.014% | 0 | 1.569% |
| MDW | DJF | 20 | 0 | 209 | 18 | 8.612% | 13.202% | 18 | 0 | 18 | 8.612% | 13.202% | 0 | 1.805% |
| MDW | DJF | 20 | 1 | 242 | 10 | 4.132% | 7.438% | 10 | 0 | 11 | 4.545% | 7.955% | 0 | 1.563% |
| MDW | DJF | 21 | 0 | 209 | 16 | 7.656% | 12.073% | 16 | 0 | 16 | 7.656% | 12.073% | 0 | 1.805% |
| MDW | DJF | 21 | 1 | 242 | 6 | 2.479% | 5.303% | 6 | 0 | 8 | 3.306% | 6.386% | 0 | 1.563% |
| MDW | DJF | 22 | 0 | 209 | 10 | 4.785% | 8.582% | 10 | 0 | 10 | 4.785% | 8.582% | 0 | 1.805% |
| MDW | DJF | 22 | 1 | 242 | 3 | 1.240% | 3.581% | 3 | 0 | 5 | 2.066% | 4.745% | 0 | 1.563% |
| MDW | DJF | 23 | 0 | 204 | 0 | 0.000% | 1.848% | 0 | 0 | 0 | 0.000% | 1.848% | 0 | 1.848% |
| MDW | DJF | 23 | 1 | 247 | 0 | 0.000% | 1.531% | 0 | 0 | 0 | 0.000% | 1.531% | 0 | 1.531% |
| MDW | JJA | 00 | 0 | 239 | 232 | 97.071% | 98.574% | 232 | 0 | 232 | 97.071% | 98.574% | 0 | 1.582% |
| MDW | JJA | 00 | 1 | 220 | 211 | 95.909% | 97.833% | 211 | 0 | 213 | 96.818% | 98.450% | 0 | 1.716% |
| MDW | JJA | 01 | 0 | 235 | 228 | 97.021% | 98.550% | 228 | 0 | 228 | 97.021% | 98.550% | 0 | 1.608% |
| MDW | JJA | 01 | 1 | 224 | 215 | 95.982% | 97.872% | 215 | 0 | 217 | 96.875% | 98.478% | 0 | 1.686% |
| MDW | JJA | 02 | 0 | 239 | 232 | 97.071% | 98.574% | 232 | 0 | 232 | 97.071% | 98.574% | 0 | 1.582% |
| MDW | JJA | 02 | 1 | 220 | 211 | 95.909% | 97.833% | 211 | 0 | 213 | 96.818% | 98.450% | 0 | 1.716% |
| MDW | JJA | 03 | 0 | 245 | 238 | 97.143% | 98.609% | 238 | 0 | 238 | 97.143% | 98.609% | 0 | 1.544% |
| MDW | JJA | 03 | 1 | 214 | 205 | 95.794% | 97.772% | 205 | 0 | 207 | 96.729% | 98.407% | 0 | 1.763% |
| MDW | JJA | 04 | 0 | 242 | 235 | 97.107% | 98.592% | 235 | 0 | 235 | 97.107% | 98.592% | 0 | 1.563% |
| MDW | JJA | 04 | 1 | 217 | 208 | 95.853% | 97.803% | 208 | 0 | 210 | 96.774% | 98.429% | 0 | 1.739% |
| MDW | JJA | 05 | 0 | 241 | 234 | 97.095% | 98.586% | 234 | 0 | 234 | 97.095% | 98.586% | 0 | 1.569% |
| MDW | JJA | 05 | 1 | 218 | 207 | 94.954% | 97.159% | 207 | 0 | 210 | 96.330% | 98.129% | 0 | 1.732% |
| MDW | JJA | 06 | 0 | 249 | 240 | 96.386% | 98.087% | 240 | 0 | 240 | 96.386% | 98.087% | 0 | 1.519% |
| MDW | JJA | 06 | 1 | 210 | 200 | 95.238% | 97.393% | 200 | 0 | 202 | 96.190% | 98.057% | 0 | 1.796% |
| MDW | JJA | 07 | 0 | 247 | 236 | 95.547% | 97.495% | 236 | 0 | 236 | 95.547% | 97.495% | 0 | 1.531% |
| MDW | JJA | 07 | 1 | 212 | 203 | 95.755% | 97.751% | 203 | 0 | 204 | 96.226% | 98.076% | 0 | 1.780% |
| MDW | JJA | 08 | 0 | 260 | 246 | 94.615% | 96.766% | 246 | 0 | 246 | 94.615% | 96.766% | 0 | 1.456% |
| MDW | JJA | 08 | 1 | 199 | 187 | 93.970% | 96.517% | 187 | 0 | 188 | 94.472% | 96.886% | 0 | 1.894% |
| MDW | JJA | 09 | 0 | 241 | 222 | 92.116% | 94.895% | 222 | 0 | 222 | 92.116% | 94.895% | 0 | 1.569% |
| MDW | JJA | 09 | 1 | 218 | 193 | 88.532% | 92.111% | 193 | 0 | 199 | 91.284% | 94.349% | 0 | 1.732% |
| MDW | JJA | 10 | 0 | 236 | 201 | 85.169% | 89.139% | 201 | 0 | 201 | 85.169% | 89.139% | 0 | 1.602% |
| MDW | JJA | 10 | 1 | 223 | 176 | 78.924% | 83.764% | 176 | 0 | 191 | 85.650% | 89.648% | 0 | 1.693% |
| MDW | JJA | 11 | 0 | 223 | 158 | 70.852% | 76.423% | 158 | 0 | 158 | 70.852% | 76.423% | 0 | 1.693% |
| MDW | JJA | 11 | 1 | 236 | 138 | 58.475% | 64.577% | 138 | 0 | 171 | 72.458% | 77.763% | 0 | 1.602% |
| MDW | JJA | 12 | 0 | 224 | 111 | 49.554% | 56.053% | 111 | 0 | 111 | 49.554% | 56.053% | 0 | 1.686% |
| MDW | JJA | 12 | 1 | 235 | 85 | 36.170% | 42.490% | 85 | 0 | 125 | 53.191% | 59.469% | 0 | 1.608% |
| MDW | JJA | 13 | 0 | 224 | 59 | 26.339% | 32.472% | 59 | 0 | 59 | 26.339% | 32.472% | 0 | 1.686% |
| MDW | JJA | 13 | 1 | 235 | 43 | 18.298% | 23.738% | 43 | 0 | 66 | 28.085% | 34.148% | 0 | 1.608% |
| MDW | JJA | 14 | 0 | 224 | 20 | 8.929% | 13.388% | 20 | 0 | 20 | 8.929% | 13.388% | 0 | 1.686% |
| MDW | JJA | 14 | 1 | 235 | 13 | 5.532% | 9.233% | 13 | 0 | 23 | 9.787% | 14.258% | 0 | 1.608% |
| MDW | JJA | 15 | 0 | 223 | 6 | 2.691% | 5.745% | 6 | 0 | 6 | 2.691% | 5.745% | 0 | 1.693% |
| MDW | JJA | 15 | 1 | 236 | 3 | 1.271% | 3.670% | 3 | 0 | 7 | 2.966% | 5.995% | 0 | 1.602% |
| MDW | JJA | 16 | 0 | 223 | 1 | 0.448% | 2.496% | 1 | 0 | 1 | 0.448% | 2.496% | 0 | 1.693% |
| MDW | JJA | 16 | 1 | 236 | 0 | 0.000% | 1.602% | 0 | 0 | 2 | 0.847% | 3.037% | 0 | 1.602% |
| MDW | JJA | 17 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 17 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 18 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 18 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 19 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 19 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 20 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 20 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 21 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 21 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 22 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 22 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | JJA | 23 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| MDW | JJA | 23 | 1 | 235 | 0 | 0.000% | 1.608% | 0 | 0 | 0 | 0.000% | 1.608% | 0 | 1.608% |
| MDW | MAM | 00 | 0 | 236 | 209 | 88.559% | 92.017% | 209 | 0 | 209 | 88.559% | 92.017% | 0 | 1.602% |
| MDW | MAM | 00 | 1 | 224 | 199 | 88.839% | 92.325% | 199 | 0 | 203 | 90.625% | 93.786% | 0 | 1.686% |
| MDW | MAM | 01 | 0 | 236 | 209 | 88.559% | 92.017% | 209 | 0 | 209 | 88.559% | 92.017% | 0 | 1.602% |
| MDW | MAM | 01 | 1 | 224 | 197 | 87.946% | 91.582% | 197 | 0 | 201 | 89.732% | 93.060% | 0 | 1.686% |
| MDW | MAM | 02 | 0 | 239 | 211 | 88.285% | 91.769% | 211 | 0 | 211 | 88.285% | 91.769% | 0 | 1.582% |
| MDW | MAM | 02 | 1 | 221 | 195 | 88.235% | 91.844% | 195 | 0 | 198 | 89.593% | 92.965% | 0 | 1.709% |
| MDW | MAM | 03 | 0 | 237 | 209 | 88.186% | 91.698% | 209 | 0 | 209 | 88.186% | 91.698% | 0 | 1.595% |
| MDW | MAM | 03 | 1 | 223 | 196 | 87.892% | 91.544% | 196 | 0 | 199 | 89.238% | 92.660% | 0 | 1.693% |
| MDW | MAM | 04 | 0 | 237 | 209 | 88.186% | 91.698% | 209 | 0 | 209 | 88.186% | 91.698% | 0 | 1.595% |
| MDW | MAM | 04 | 1 | 223 | 196 | 87.892% | 91.544% | 196 | 0 | 199 | 89.238% | 92.660% | 0 | 1.693% |
| MDW | MAM | 05 | 0 | 238 | 210 | 88.235% | 91.734% | 210 | 0 | 210 | 88.235% | 91.734% | 0 | 1.588% |
| MDW | MAM | 05 | 1 | 222 | 195 | 87.838% | 91.505% | 195 | 0 | 198 | 89.189% | 92.627% | 0 | 1.701% |
| MDW | MAM | 06 | 0 | 244 | 215 | 88.115% | 91.596% | 215 | 0 | 215 | 88.115% | 91.596% | 0 | 1.550% |
| MDW | MAM | 06 | 1 | 216 | 187 | 86.574% | 90.487% | 187 | 0 | 190 | 87.963% | 91.652% | 0 | 1.747% |
| MDW | MAM | 07 | 0 | 224 | 194 | 86.607% | 90.455% | 194 | 0 | 194 | 86.607% | 90.455% | 0 | 1.686% |
| MDW | MAM | 07 | 1 | 236 | 202 | 85.593% | 89.504% | 202 | 0 | 207 | 87.712% | 91.306% | 0 | 1.602% |
| MDW | MAM | 08 | 0 | 241 | 207 | 85.892% | 89.725% | 207 | 0 | 207 | 85.892% | 89.725% | 0 | 1.569% |
| MDW | MAM | 08 | 1 | 219 | 185 | 84.475% | 88.672% | 185 | 0 | 190 | 86.758% | 90.619% | 0 | 1.724% |
| MDW | MAM | 09 | 0 | 250 | 205 | 82.000% | 86.267% | 205 | 0 | 205 | 82.000% | 86.267% | 0 | 1.513% |
| MDW | MAM | 09 | 1 | 210 | 158 | 75.238% | 80.588% | 158 | 0 | 173 | 82.381% | 86.939% | 0 | 1.796% |
| MDW | MAM | 10 | 0 | 246 | 187 | 76.016% | 80.926% | 187 | 0 | 187 | 76.016% | 80.926% | 0 | 1.538% |
| MDW | MAM | 10 | 1 | 214 | 150 | 70.093% | 75.829% | 150 | 0 | 168 | 78.505% | 83.480% | 0 | 1.763% |
| MDW | MAM | 11 | 0 | 230 | 148 | 64.348% | 70.256% | 148 | 0 | 148 | 64.348% | 70.256% | 0 | 1.643% |
| MDW | MAM | 11 | 1 | 230 | 144 | 62.609% | 68.606% | 144 | 0 | 169 | 73.478% | 78.764% | 0 | 1.643% |
| MDW | MAM | 12 | 0 | 230 | 119 | 51.739% | 58.115% | 119 | 0 | 119 | 51.739% | 58.115% | 0 | 1.643% |
| MDW | MAM | 12 | 1 | 230 | 106 | 46.087% | 52.540% | 106 | 0 | 127 | 55.217% | 61.506% | 0 | 1.643% |
| MDW | MAM | 13 | 0 | 239 | 94 | 39.331% | 45.645% | 94 | 0 | 94 | 39.331% | 45.645% | 0 | 1.582% |
| MDW | MAM | 13 | 1 | 221 | 51 | 23.077% | 29.063% | 51 | 0 | 69 | 31.222% | 37.608% | 0 | 1.709% |
| MDW | MAM | 14 | 0 | 222 | 44 | 19.820% | 25.558% | 44 | 0 | 44 | 19.820% | 25.558% | 0 | 1.701% |
| MDW | MAM | 14 | 1 | 238 | 18 | 7.563% | 11.637% | 18 | 0 | 41 | 17.227% | 22.535% | 0 | 1.588% |
| MDW | MAM | 15 | 0 | 229 | 17 | 7.424% | 11.566% | 17 | 0 | 17 | 7.424% | 11.566% | 0 | 1.650% |
| MDW | MAM | 15 | 1 | 231 | 7 | 3.030% | 6.122% | 7 | 0 | 13 | 5.628% | 9.389% | 0 | 1.636% |
| MDW | MAM | 16 | 0 | 230 | 9 | 3.913% | 7.268% | 9 | 0 | 9 | 3.913% | 7.268% | 0 | 1.643% |
| MDW | MAM | 16 | 1 | 230 | 4 | 1.739% | 4.386% | 4 | 0 | 5 | 2.174% | 4.987% | 0 | 1.643% |
| MDW | MAM | 17 | 0 | 232 | 8 | 3.448% | 6.656% | 8 | 0 | 8 | 3.448% | 6.656% | 0 | 1.629% |
| MDW | MAM | 17 | 1 | 228 | 2 | 0.877% | 3.141% | 2 | 0 | 3 | 1.316% | 3.796% | 0 | 1.657% |
| MDW | MAM | 18 | 0 | 230 | 5 | 2.174% | 4.987% | 5 | 0 | 5 | 2.174% | 4.987% | 0 | 1.643% |
| MDW | MAM | 18 | 1 | 230 | 2 | 0.870% | 3.115% | 2 | 0 | 2 | 0.870% | 3.115% | 0 | 1.643% |
| MDW | MAM | 19 | 0 | 229 | 4 | 1.747% | 4.404% | 4 | 0 | 4 | 1.747% | 4.404% | 0 | 1.650% |
| MDW | MAM | 19 | 1 | 231 | 3 | 1.299% | 3.748% | 3 | 0 | 3 | 1.299% | 3.748% | 0 | 1.636% |
| MDW | MAM | 20 | 0 | 228 | 2 | 0.877% | 3.141% | 2 | 0 | 2 | 0.877% | 3.141% | 0 | 1.657% |
| MDW | MAM | 20 | 1 | 232 | 2 | 0.862% | 3.088% | 2 | 0 | 4 | 1.724% | 4.348% | 0 | 1.629% |
| MDW | MAM | 21 | 0 | 230 | 2 | 0.870% | 3.115% | 2 | 0 | 2 | 0.870% | 3.115% | 0 | 1.643% |
| MDW | MAM | 21 | 1 | 230 | 1 | 0.435% | 2.421% | 1 | 0 | 2 | 0.870% | 3.115% | 0 | 1.643% |
| MDW | MAM | 22 | 0 | 229 | 1 | 0.437% | 2.432% | 1 | 0 | 1 | 0.437% | 2.432% | 0 | 1.650% |
| MDW | MAM | 22 | 1 | 231 | 0 | 0.000% | 1.636% | 0 | 0 | 1 | 0.433% | 2.411% | 0 | 1.636% |
| MDW | MAM | 23 | 0 | 229 | 0 | 0.000% | 1.650% | 0 | 0 | 0 | 0.000% | 1.650% | 0 | 1.650% |
| MDW | MAM | 23 | 1 | 231 | 0 | 0.000% | 1.636% | 0 | 0 | 0 | 0.000% | 1.636% | 0 | 1.636% |
| MDW | SON | 00 | 0 | 208 | 189 | 90.865% | 94.074% | 189 | 0 | 189 | 90.865% | 94.074% | 0 | 1.813% |
| MDW | SON | 00 | 1 | 247 | 219 | 88.664% | 92.040% | 219 | 0 | 227 | 91.903% | 94.697% | 0 | 1.531% |
| MDW | SON | 01 | 0 | 209 | 190 | 90.909% | 94.103% | 190 | 0 | 190 | 90.909% | 94.103% | 0 | 1.805% |
| MDW | SON | 01 | 1 | 246 | 216 | 87.805% | 91.323% | 216 | 0 | 224 | 91.057% | 94.020% | 0 | 1.538% |
| MDW | SON | 02 | 0 | 206 | 187 | 90.777% | 94.016% | 187 | 0 | 187 | 90.777% | 94.016% | 0 | 1.831% |
| MDW | SON | 02 | 1 | 249 | 218 | 87.550% | 91.089% | 218 | 0 | 226 | 90.763% | 93.766% | 0 | 1.519% |
| MDW | SON | 03 | 0 | 202 | 183 | 90.594% | 93.896% | 183 | 0 | 183 | 90.594% | 93.896% | 0 | 1.866% |
| MDW | SON | 03 | 1 | 253 | 221 | 87.352% | 90.896% | 221 | 0 | 230 | 90.909% | 93.866% | 0 | 1.496% |
| MDW | SON | 04 | 0 | 194 | 175 | 90.206% | 93.640% | 175 | 0 | 175 | 90.206% | 93.640% | 0 | 1.942% |
| MDW | SON | 04 | 1 | 261 | 229 | 87.739% | 91.180% | 229 | 0 | 238 | 91.188% | 94.056% | 0 | 1.450% |
| MDW | SON | 05 | 0 | 196 | 176 | 89.796% | 93.297% | 176 | 0 | 176 | 89.796% | 93.297% | 0 | 1.922% |
| MDW | SON | 05 | 1 | 259 | 226 | 87.259% | 90.782% | 226 | 0 | 236 | 91.120% | 94.010% | 0 | 1.462% |
| MDW | SON | 06 | 0 | 194 | 173 | 89.175% | 92.810% | 173 | 0 | 173 | 89.175% | 92.810% | 0 | 1.942% |
| MDW | SON | 06 | 1 | 261 | 226 | 86.590% | 90.197% | 226 | 0 | 237 | 90.805% | 93.743% | 0 | 1.450% |
| MDW | SON | 07 | 0 | 211 | 189 | 89.573% | 93.013% | 189 | 0 | 189 | 89.573% | 93.013% | 0 | 1.788% |
| MDW | SON | 07 | 1 | 244 | 209 | 85.656% | 89.502% | 209 | 0 | 219 | 89.754% | 92.963% | 0 | 1.550% |
| MDW | SON | 08 | 0 | 220 | 197 | 89.545% | 92.932% | 197 | 0 | 197 | 89.545% | 92.932% | 0 | 1.716% |
| MDW | SON | 08 | 1 | 235 | 197 | 83.830% | 87.987% | 197 | 0 | 207 | 88.085% | 91.627% | 0 | 1.608% |
| MDW | SON | 09 | 0 | 228 | 203 | 89.035% | 92.462% | 203 | 0 | 203 | 89.035% | 92.462% | 0 | 1.657% |
| MDW | SON | 09 | 1 | 227 | 178 | 78.414% | 83.270% | 178 | 0 | 193 | 85.022% | 89.079% | 0 | 1.664% |
| MDW | SON | 10 | 0 | 226 | 188 | 83.186% | 87.498% | 188 | 0 | 188 | 83.186% | 87.498% | 0 | 1.671% |
| MDW | SON | 10 | 1 | 229 | 161 | 70.306% | 75.849% | 161 | 0 | 178 | 77.729% | 82.635% | 0 | 1.650% |
| MDW | SON | 11 | 0 | 210 | 146 | 69.524% | 75.353% | 146 | 0 | 146 | 69.524% | 75.353% | 0 | 1.796% |
| MDW | SON | 11 | 1 | 245 | 136 | 55.510% | 61.600% | 136 | 0 | 158 | 64.490% | 70.216% | 0 | 1.544% |
| MDW | SON | 12 | 0 | 195 | 105 | 53.846% | 60.701% | 105 | 0 | 105 | 53.846% | 60.701% | 0 | 1.932% |
| MDW | SON | 12 | 1 | 260 | 75 | 28.846% | 34.629% | 75 | 0 | 114 | 43.846% | 49.924% | 0 | 1.456% |
| MDW | SON | 13 | 0 | 194 | 52 | 26.804% | 33.443% | 52 | 0 | 52 | 26.804% | 33.443% | 0 | 1.942% |
| MDW | SON | 13 | 1 | 261 | 30 | 11.494% | 15.934% | 30 | 0 | 58 | 22.222% | 27.648% | 0 | 1.450% |
| MDW | SON | 14 | 0 | 193 | 20 | 10.363% | 15.464% | 20 | 0 | 20 | 10.363% | 15.464% | 0 | 1.952% |
| MDW | SON | 14 | 1 | 262 | 11 | 4.198% | 7.360% | 11 | 0 | 21 | 8.015% | 11.942% | 0 | 1.445% |
| MDW | SON | 15 | 0 | 191 | 7 | 3.665% | 7.370% | 7 | 0 | 7 | 3.665% | 7.370% | 0 | 1.972% |
| MDW | SON | 15 | 1 | 264 | 8 | 3.030% | 5.865% | 8 | 0 | 10 | 3.788% | 6.831% | 0 | 1.434% |
| MDW | SON | 16 | 0 | 190 | 6 | 3.158% | 6.717% | 6 | 0 | 6 | 3.158% | 6.717% | 0 | 1.982% |
| MDW | SON | 16 | 1 | 265 | 6 | 2.264% | 4.851% | 6 | 0 | 8 | 3.019% | 5.843% | 0 | 1.429% |
| MDW | SON | 17 | 0 | 188 | 3 | 1.596% | 4.586% | 3 | 0 | 3 | 1.596% | 4.586% | 0 | 2.002% |
| MDW | SON | 17 | 1 | 267 | 2 | 0.749% | 2.690% | 2 | 0 | 4 | 1.498% | 3.788% | 0 | 1.418% |
| MDW | SON | 18 | 0 | 186 | 1 | 0.538% | 2.982% | 1 | 0 | 1 | 0.538% | 2.982% | 0 | 2.024% |
| MDW | SON | 18 | 1 | 269 | 3 | 1.115% | 3.227% | 3 | 0 | 6 | 2.230% | 4.780% | 0 | 1.408% |
| MDW | SON | 19 | 0 | 186 | 1 | 0.538% | 2.982% | 1 | 0 | 1 | 0.538% | 2.982% | 0 | 2.024% |
| MDW | SON | 19 | 1 | 269 | 3 | 1.115% | 3.227% | 3 | 0 | 6 | 2.230% | 4.780% | 0 | 1.408% |
| MDW | SON | 20 | 0 | 187 | 1 | 0.535% | 2.966% | 1 | 0 | 1 | 0.535% | 2.966% | 0 | 2.013% |
| MDW | SON | 20 | 1 | 268 | 3 | 1.119% | 3.239% | 3 | 0 | 5 | 1.866% | 4.292% | 0 | 1.413% |
| MDW | SON | 21 | 0 | 187 | 1 | 0.535% | 2.966% | 1 | 0 | 1 | 0.535% | 2.966% | 0 | 2.013% |
| MDW | SON | 21 | 1 | 268 | 2 | 0.746% | 2.680% | 2 | 0 | 4 | 1.493% | 3.774% | 0 | 1.413% |
| MDW | SON | 22 | 0 | 190 | 1 | 0.526% | 2.921% | 1 | 0 | 1 | 0.526% | 2.921% | 0 | 1.982% |
| MDW | SON | 22 | 1 | 265 | 0 | 0.000% | 1.429% | 0 | 0 | 1 | 0.377% | 2.106% | 0 | 1.429% |
| MDW | SON | 23 | 0 | 190 | 0 | 0.000% | 1.982% | 0 | 0 | 0 | 0.000% | 1.982% | 0 | 1.982% |
| MDW | SON | 23 | 1 | 265 | 0 | 0.000% | 1.429% | 0 | 0 | 0 | 0.000% | 1.429% | 0 | 1.429% |
| MIA | DJF | 00 | 0 | 226 | 219 | 96.903% | 98.492% | 219 | 0 | 219 | 96.903% | 98.492% | 0 | 1.671% |
| MIA | DJF | 00 | 1 | 224 | 216 | 96.429% | 98.179% | 216 | 0 | 217 | 96.875% | 98.478% | 0 | 1.686% |
| MIA | DJF | 01 | 0 | 222 | 215 | 96.847% | 98.464% | 215 | 0 | 215 | 96.847% | 98.464% | 0 | 1.701% |
| MIA | DJF | 01 | 1 | 228 | 220 | 96.491% | 98.212% | 220 | 0 | 221 | 96.930% | 98.505% | 0 | 1.657% |
| MIA | DJF | 02 | 0 | 221 | 214 | 96.833% | 98.457% | 214 | 0 | 214 | 96.833% | 98.457% | 0 | 1.709% |
| MIA | DJF | 02 | 1 | 229 | 219 | 95.633% | 97.611% | 219 | 0 | 221 | 96.507% | 98.219% | 0 | 1.650% |
| MIA | DJF | 03 | 0 | 224 | 217 | 96.875% | 98.478% | 217 | 0 | 217 | 96.875% | 98.478% | 0 | 1.686% |
| MIA | DJF | 03 | 1 | 226 | 216 | 95.575% | 97.579% | 216 | 0 | 218 | 96.460% | 98.196% | 0 | 1.671% |
| MIA | DJF | 04 | 0 | 221 | 214 | 96.833% | 98.457% | 214 | 0 | 214 | 96.833% | 98.457% | 0 | 1.709% |
| MIA | DJF | 04 | 1 | 229 | 218 | 95.197% | 97.297% | 218 | 0 | 221 | 96.507% | 98.219% | 0 | 1.650% |
| MIA | DJF | 05 | 0 | 220 | 213 | 96.818% | 98.450% | 213 | 0 | 213 | 96.818% | 98.450% | 0 | 1.716% |
| MIA | DJF | 05 | 1 | 230 | 219 | 95.217% | 97.309% | 219 | 0 | 222 | 96.522% | 98.227% | 0 | 1.643% |
| MIA | DJF | 06 | 0 | 218 | 211 | 96.789% | 98.436% | 211 | 0 | 211 | 96.789% | 98.436% | 0 | 1.732% |
| MIA | DJF | 06 | 1 | 232 | 221 | 95.259% | 97.332% | 221 | 0 | 224 | 96.552% | 98.243% | 0 | 1.629% |
| MIA | DJF | 07 | 0 | 218 | 211 | 96.789% | 98.436% | 211 | 0 | 211 | 96.789% | 98.436% | 0 | 1.732% |
| MIA | DJF | 07 | 1 | 232 | 220 | 94.828% | 97.017% | 220 | 0 | 224 | 96.552% | 98.243% | 0 | 1.629% |
| MIA | DJF | 08 | 0 | 262 | 253 | 96.565% | 98.182% | 253 | 0 | 253 | 96.565% | 98.182% | 0 | 1.445% |
| MIA | DJF | 08 | 1 | 188 | 177 | 94.149% | 96.702% | 177 | 0 | 180 | 95.745% | 97.828% | 0 | 2.002% |
| MIA | DJF | 09 | 0 | 297 | 283 | 95.286% | 97.172% | 283 | 0 | 283 | 95.286% | 97.172% | 0 | 1.277% |
| MIA | DJF | 09 | 1 | 153 | 137 | 89.542% | 93.460% | 137 | 0 | 141 | 92.157% | 95.457% | 0 | 2.449% |
| MIA | DJF | 10 | 0 | 280 | 232 | 82.857% | 86.819% | 232 | 0 | 232 | 82.857% | 86.819% | 0 | 1.353% |
| MIA | DJF | 10 | 1 | 170 | 131 | 77.059% | 82.740% | 131 | 0 | 145 | 85.294% | 89.836% | 0 | 2.210% |
| MIA | DJF | 11 | 0 | 275 | 178 | 64.727% | 70.136% | 178 | 0 | 178 | 64.727% | 70.136% | 0 | 1.378% |
| MIA | DJF | 11 | 1 | 175 | 84 | 48.000% | 55.365% | 84 | 0 | 102 | 58.286% | 65.337% | 0 | 2.148% |
| MIA | DJF | 12 | 0 | 242 | 101 | 41.736% | 48.030% | 101 | 0 | 101 | 41.736% | 48.030% | 0 | 1.563% |
| MIA | DJF | 12 | 1 | 208 | 43 | 20.673% | 26.684% | 43 | 0 | 68 | 32.692% | 39.331% | 0 | 1.813% |
| MIA | DJF | 13 | 0 | 225 | 36 | 16.000% | 21.355% | 36 | 0 | 36 | 16.000% | 21.355% | 0 | 1.679% |
| MIA | DJF | 13 | 1 | 225 | 18 | 8.000% | 12.290% | 18 | 0 | 39 | 17.333% | 22.817% | 0 | 1.679% |
| MIA | DJF | 14 | 0 | 232 | 15 | 6.466% | 10.392% | 15 | 0 | 15 | 6.466% | 10.392% | 0 | 1.629% |
| MIA | DJF | 14 | 1 | 218 | 6 | 2.752% | 5.874% | 6 | 0 | 10 | 4.587% | 8.237% | 0 | 1.732% |
| MIA | DJF | 15 | 0 | 229 | 0 | 0.000% | 1.650% | 0 | 0 | 0 | 0.000% | 1.650% | 0 | 1.650% |
| MIA | DJF | 15 | 1 | 221 | 3 | 1.357% | 3.914% | 3 | 0 | 4 | 1.810% | 4.561% | 0 | 1.709% |
| MIA | DJF | 16 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 16 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 17 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 17 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 18 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 18 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 19 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 19 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 20 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 20 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 21 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 21 | 1 | 220 | 2 | 0.909% | 3.253% | 2 | 0 | 2 | 0.909% | 3.253% | 0 | 1.716% |
| MIA | DJF | 22 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 22 | 1 | 220 | 0 | 0.000% | 1.716% | 0 | 0 | 0 | 0.000% | 1.716% | 0 | 1.716% |
| MIA | DJF | 23 | 0 | 230 | 0 | 0.000% | 1.643% | 0 | 0 | 0 | 0.000% | 1.643% | 0 | 1.643% |
| MIA | DJF | 23 | 1 | 220 | 0 | 0.000% | 1.716% | 0 | 0 | 0 | 0.000% | 1.716% | 0 | 1.716% |
| MIA | JJA | 00 | 0 | 211 | 211 | 100.000% | 100.000% | 211 | 0 | 211 | 100.000% | 100.000% | 0 | 1.788% |
| MIA | JJA | 00 | 1 | 239 | 236 | 98.745% | 99.572% | 236 | 0 | 236 | 98.745% | 99.572% | 0 | 1.582% |
| MIA | JJA | 01 | 0 | 210 | 210 | 100.000% | 100.000% | 210 | 0 | 210 | 100.000% | 100.000% | 0 | 1.796% |
| MIA | JJA | 01 | 1 | 240 | 237 | 98.750% | 99.574% | 237 | 0 | 237 | 98.750% | 99.574% | 0 | 1.575% |
| MIA | JJA | 02 | 0 | 208 | 208 | 100.000% | 100.000% | 208 | 0 | 208 | 100.000% | 100.000% | 0 | 1.813% |
| MIA | JJA | 02 | 1 | 242 | 239 | 98.760% | 99.578% | 239 | 0 | 239 | 98.760% | 99.578% | 0 | 1.563% |
| MIA | JJA | 03 | 0 | 208 | 208 | 100.000% | 100.000% | 208 | 0 | 208 | 100.000% | 100.000% | 0 | 1.813% |
| MIA | JJA | 03 | 1 | 242 | 239 | 98.760% | 99.578% | 239 | 0 | 239 | 98.760% | 99.578% | 0 | 1.563% |
| MIA | JJA | 04 | 0 | 207 | 207 | 100.000% | 100.000% | 207 | 0 | 207 | 100.000% | 100.000% | 0 | 1.822% |
| MIA | JJA | 04 | 1 | 243 | 240 | 98.765% | 99.579% | 240 | 0 | 240 | 98.765% | 99.579% | 0 | 1.556% |
| MIA | JJA | 05 | 0 | 206 | 206 | 100.000% | 100.000% | 206 | 0 | 206 | 100.000% | 100.000% | 0 | 1.831% |
| MIA | JJA | 05 | 1 | 244 | 241 | 98.770% | 99.581% | 241 | 0 | 241 | 98.770% | 99.581% | 0 | 1.550% |
| MIA | JJA | 06 | 0 | 214 | 214 | 100.000% | 100.000% | 214 | 0 | 214 | 100.000% | 100.000% | 0 | 1.763% |
| MIA | JJA | 06 | 1 | 236 | 233 | 98.729% | 99.567% | 233 | 0 | 233 | 98.729% | 99.567% | 0 | 1.602% |
| MIA | JJA | 07 | 0 | 149 | 149 | 100.000% | 100.000% | 149 | 0 | 149 | 100.000% | 100.000% | 0 | 2.513% |
| MIA | JJA | 07 | 1 | 301 | 298 | 99.003% | 99.660% | 298 | 0 | 298 | 99.003% | 99.660% | 0 | 1.260% |
| MIA | JJA | 08 | 0 | 71 | 70 | 98.592% | 99.751% | 70 | 0 | 70 | 98.592% | 99.751% | 0 | 5.133% |
| MIA | JJA | 08 | 1 | 379 | 358 | 94.459% | 96.348% | 358 | 0 | 366 | 96.570% | 97.985% | 0 | 1.003% |
| MIA | JJA | 09 | 0 | 83 | 80 | 96.386% | 98.763% | 80 | 0 | 80 | 96.386% | 98.763% | 0 | 4.424% |
| MIA | JJA | 09 | 1 | 367 | 273 | 74.387% | 78.584% | 273 | 0 | 328 | 89.373% | 92.128% | 0 | 1.036% |
| MIA | JJA | 10 | 0 | 143 | 96 | 67.133% | 74.295% | 96 | 0 | 96 | 67.133% | 74.295% | 0 | 2.616% |
| MIA | JJA | 10 | 1 | 307 | 124 | 40.391% | 45.966% | 124 | 0 | 208 | 67.752% | 72.734% | 0 | 1.236% |
| MIA | JJA | 11 | 0 | 182 | 69 | 37.912% | 45.142% | 69 | 0 | 69 | 37.912% | 45.142% | 0 | 2.067% |
| MIA | JJA | 11 | 1 | 268 | 54 | 20.149% | 25.358% | 54 | 0 | 120 | 44.776% | 50.762% | 0 | 1.413% |
| MIA | JJA | 12 | 0 | 203 | 31 | 15.271% | 20.860% | 31 | 0 | 31 | 15.271% | 20.860% | 0 | 1.857% |
| MIA | JJA | 12 | 1 | 247 | 34 | 13.765% | 18.620% | 34 | 0 | 72 | 29.150% | 35.102% | 0 | 1.531% |
| MIA | JJA | 13 | 0 | 225 | 14 | 6.222% | 10.172% | 14 | 0 | 14 | 6.222% | 10.172% | 0 | 1.679% |
| MIA | JJA | 13 | 1 | 225 | 14 | 6.222% | 10.172% | 14 | 0 | 25 | 11.111% | 15.888% | 0 | 1.679% |
| MIA | JJA | 14 | 0 | 225 | 4 | 1.778% | 4.481% | 4 | 0 | 4 | 1.778% | 4.481% | 0 | 1.679% |
| MIA | JJA | 14 | 1 | 225 | 4 | 1.778% | 4.481% | 4 | 0 | 8 | 3.556% | 6.858% | 0 | 1.679% |
| MIA | JJA | 15 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 15 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 16 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 16 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 17 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 17 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 18 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 18 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 19 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 19 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 20 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 20 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 21 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 21 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 22 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 22 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | JJA | 23 | 0 | 227 | 0 | 0.000% | 1.664% | 0 | 0 | 0 | 0.000% | 1.664% | 0 | 1.664% |
| MIA | JJA | 23 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| MIA | MAM | 00 | 0 | 309 | 307 | 99.353% | 99.822% | 307 | 0 | 307 | 99.353% | 99.822% | 0 | 1.228% |
| MIA | MAM | 00 | 1 | 147 | 147 | 100.000% | 100.000% | 147 | 0 | 147 | 100.000% | 100.000% | 0 | 2.547% |
| MIA | MAM | 01 | 0 | 306 | 304 | 99.346% | 99.821% | 304 | 0 | 304 | 99.346% | 99.821% | 0 | 1.240% |
| MIA | MAM | 01 | 1 | 150 | 149 | 99.333% | 99.882% | 149 | 0 | 150 | 100.000% | 100.000% | 0 | 2.497% |
| MIA | MAM | 02 | 0 | 306 | 304 | 99.346% | 99.821% | 304 | 0 | 304 | 99.346% | 99.821% | 0 | 1.240% |
| MIA | MAM | 02 | 1 | 150 | 149 | 99.333% | 99.882% | 149 | 0 | 150 | 100.000% | 100.000% | 0 | 2.497% |
| MIA | MAM | 03 | 0 | 308 | 306 | 99.351% | 99.822% | 306 | 0 | 306 | 99.351% | 99.822% | 0 | 1.232% |
| MIA | MAM | 03 | 1 | 148 | 147 | 99.324% | 99.881% | 147 | 0 | 148 | 100.000% | 100.000% | 0 | 2.530% |
| MIA | MAM | 04 | 0 | 305 | 303 | 99.344% | 99.820% | 303 | 0 | 303 | 99.344% | 99.820% | 0 | 1.244% |
| MIA | MAM | 04 | 1 | 151 | 149 | 98.675% | 99.636% | 149 | 0 | 151 | 100.000% | 100.000% | 0 | 2.481% |
| MIA | MAM | 05 | 0 | 310 | 308 | 99.355% | 99.823% | 308 | 0 | 308 | 99.355% | 99.823% | 0 | 1.224% |
| MIA | MAM | 05 | 1 | 146 | 144 | 98.630% | 99.624% | 144 | 0 | 146 | 100.000% | 100.000% | 0 | 2.564% |
| MIA | MAM | 06 | 0 | 305 | 303 | 99.344% | 99.820% | 303 | 0 | 303 | 99.344% | 99.820% | 0 | 1.244% |
| MIA | MAM | 06 | 1 | 151 | 149 | 98.675% | 99.636% | 149 | 0 | 151 | 100.000% | 100.000% | 0 | 2.481% |
| MIA | MAM | 07 | 0 | 296 | 293 | 98.986% | 99.655% | 293 | 0 | 293 | 98.986% | 99.655% | 0 | 1.281% |
| MIA | MAM | 07 | 1 | 160 | 159 | 99.375% | 99.890% | 159 | 0 | 160 | 100.000% | 100.000% | 0 | 2.345% |
| MIA | MAM | 08 | 0 | 294 | 289 | 98.299% | 99.271% | 289 | 0 | 289 | 98.299% | 99.271% | 0 | 1.290% |
| MIA | MAM | 08 | 1 | 162 | 159 | 98.148% | 99.368% | 159 | 0 | 160 | 98.765% | 99.661% | 0 | 2.316% |
| MIA | MAM | 09 | 0 | 224 | 209 | 93.304% | 95.900% | 209 | 0 | 209 | 93.304% | 95.900% | 0 | 1.686% |
| MIA | MAM | 09 | 1 | 232 | 213 | 91.810% | 94.695% | 213 | 0 | 223 | 96.121% | 97.946% | 0 | 1.629% |
| MIA | MAM | 10 | 0 | 194 | 164 | 84.536% | 88.948% | 164 | 0 | 164 | 84.536% | 88.948% | 0 | 1.942% |
| MIA | MAM | 10 | 1 | 262 | 188 | 71.756% | 76.862% | 188 | 0 | 211 | 80.534% | 84.873% | 0 | 1.445% |
| MIA | MAM | 11 | 0 | 164 | 105 | 64.024% | 70.971% | 105 | 0 | 105 | 64.024% | 70.971% | 0 | 2.289% |
| MIA | MAM | 11 | 1 | 292 | 117 | 40.068% | 45.783% | 117 | 0 | 147 | 50.342% | 56.035% | 0 | 1.298% |
| MIA | MAM | 12 | 0 | 159 | 59 | 37.107% | 44.837% | 59 | 0 | 59 | 37.107% | 44.837% | 0 | 2.359% |
| MIA | MAM | 12 | 1 | 297 | 54 | 18.182% | 22.965% | 54 | 0 | 84 | 28.283% | 33.657% | 0 | 1.277% |
| MIA | MAM | 13 | 0 | 171 | 35 | 20.468% | 27.132% | 35 | 0 | 35 | 20.468% | 27.132% | 0 | 2.197% |
| MIA | MAM | 13 | 1 | 285 | 12 | 4.211% | 7.214% | 12 | 0 | 21 | 7.368% | 11.001% | 0 | 1.330% |
| MIA | MAM | 14 | 0 | 162 | 13 | 8.025% | 13.245% | 13 | 0 | 13 | 8.025% | 13.245% | 0 | 2.316% |
| MIA | MAM | 14 | 1 | 294 | 2 | 0.680% | 2.446% | 2 | 0 | 6 | 2.041% | 4.380% | 0 | 1.290% |
| MIA | MAM | 15 | 0 | 160 | 2 | 1.250% | 4.443% | 2 | 0 | 2 | 1.250% | 4.443% | 0 | 2.345% |
| MIA | MAM | 15 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 2 | 0.676% | 2.430% | 0 | 1.281% |
| MIA | MAM | 16 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 16 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 17 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 17 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 18 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 18 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 19 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 19 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 20 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 20 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 21 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 21 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 22 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 22 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | MAM | 23 | 0 | 160 | 0 | 0.000% | 2.345% | 0 | 0 | 0 | 0.000% | 2.345% | 0 | 2.345% |
| MIA | MAM | 23 | 1 | 296 | 0 | 0.000% | 1.281% | 0 | 0 | 0 | 0.000% | 1.281% | 0 | 1.281% |
| MIA | SON | 00 | 0 | 319 | 314 | 98.433% | 99.329% | 314 | 0 | 314 | 98.433% | 99.329% | 0 | 1.190% |
| MIA | SON | 00 | 1 | 133 | 132 | 99.248% | 99.867% | 132 | 0 | 132 | 99.248% | 99.867% | 0 | 2.807% |
| MIA | SON | 01 | 0 | 319 | 314 | 98.433% | 99.329% | 314 | 0 | 314 | 98.433% | 99.329% | 0 | 1.190% |
| MIA | SON | 01 | 1 | 133 | 132 | 99.248% | 99.867% | 132 | 0 | 132 | 99.248% | 99.867% | 0 | 2.807% |
| MIA | SON | 02 | 0 | 316 | 311 | 98.418% | 99.322% | 311 | 0 | 311 | 98.418% | 99.322% | 0 | 1.201% |
| MIA | SON | 02 | 1 | 136 | 135 | 99.265% | 99.870% | 135 | 0 | 135 | 99.265% | 99.870% | 0 | 2.747% |
| MIA | SON | 03 | 0 | 317 | 312 | 98.423% | 99.324% | 312 | 0 | 312 | 98.423% | 99.324% | 0 | 1.197% |
| MIA | SON | 03 | 1 | 135 | 134 | 99.259% | 99.869% | 134 | 0 | 134 | 99.259% | 99.869% | 0 | 2.767% |
| MIA | SON | 04 | 0 | 313 | 308 | 98.403% | 99.316% | 308 | 0 | 308 | 98.403% | 99.316% | 0 | 1.212% |
| MIA | SON | 04 | 1 | 139 | 138 | 99.281% | 99.873% | 138 | 0 | 138 | 99.281% | 99.873% | 0 | 2.689% |
| MIA | SON | 05 | 0 | 315 | 309 | 98.095% | 99.124% | 309 | 0 | 309 | 98.095% | 99.124% | 0 | 1.205% |
| MIA | SON | 05 | 1 | 137 | 136 | 99.270% | 99.871% | 136 | 0 | 136 | 99.270% | 99.871% | 0 | 2.728% |
| MIA | SON | 06 | 0 | 316 | 310 | 98.101% | 99.127% | 310 | 0 | 310 | 98.101% | 99.127% | 0 | 1.201% |
| MIA | SON | 06 | 1 | 136 | 135 | 99.265% | 99.870% | 135 | 0 | 135 | 99.265% | 99.870% | 0 | 2.747% |
| MIA | SON | 07 | 0 | 264 | 258 | 97.727% | 98.954% | 258 | 0 | 258 | 97.727% | 98.954% | 0 | 1.434% |
| MIA | SON | 07 | 1 | 188 | 186 | 98.936% | 99.708% | 186 | 0 | 186 | 98.936% | 99.708% | 0 | 2.002% |
| MIA | SON | 08 | 0 | 211 | 204 | 96.682% | 98.384% | 204 | 0 | 204 | 96.682% | 98.384% | 0 | 1.788% |
| MIA | SON | 08 | 1 | 241 | 235 | 97.510% | 98.854% | 235 | 0 | 237 | 98.340% | 99.353% | 0 | 1.569% |
| MIA | SON | 09 | 0 | 157 | 146 | 92.994% | 96.043% | 146 | 0 | 146 | 92.994% | 96.043% | 0 | 2.388% |
| MIA | SON | 09 | 1 | 295 | 251 | 85.085% | 88.698% | 251 | 0 | 268 | 90.847% | 93.634% | 0 | 1.285% |
| MIA | SON | 10 | 0 | 146 | 115 | 78.767% | 84.619% | 115 | 0 | 115 | 78.767% | 84.619% | 0 | 2.564% |
| MIA | SON | 10 | 1 | 306 | 172 | 56.209% | 61.657% | 172 | 0 | 219 | 71.569% | 76.331% | 0 | 1.240% |
| MIA | SON | 11 | 0 | 159 | 80 | 50.314% | 57.986% | 80 | 0 | 80 | 50.314% | 57.986% | 0 | 2.359% |
| MIA | SON | 11 | 1 | 293 | 101 | 34.471% | 40.082% | 101 | 0 | 135 | 46.075% | 51.797% | 0 | 1.294% |
| MIA | SON | 12 | 0 | 166 | 41 | 24.699% | 31.782% | 41 | 0 | 41 | 24.699% | 31.782% | 0 | 2.262% |
| MIA | SON | 12 | 1 | 286 | 42 | 14.685% | 19.255% | 42 | 0 | 63 | 22.028% | 27.184% | 0 | 1.325% |
| MIA | SON | 13 | 0 | 176 | 21 | 11.932% | 17.552% | 21 | 0 | 21 | 11.932% | 17.552% | 0 | 2.136% |
| MIA | SON | 13 | 1 | 276 | 11 | 3.986% | 6.995% | 11 | 0 | 20 | 7.246% | 10.927% | 0 | 1.373% |
| MIA | SON | 14 | 0 | 172 | 5 | 2.907% | 6.624% | 5 | 0 | 5 | 2.907% | 6.624% | 0 | 2.185% |
| MIA | SON | 14 | 1 | 280 | 3 | 1.071% | 3.102% | 3 | 0 | 5 | 1.786% | 4.111% | 0 | 1.353% |
| MIA | SON | 15 | 0 | 172 | 2 | 1.163% | 4.140% | 2 | 0 | 2 | 1.163% | 4.140% | 0 | 2.185% |
| MIA | SON | 15 | 1 | 280 | 1 | 0.357% | 1.995% | 1 | 0 | 1 | 0.357% | 1.995% | 0 | 1.353% |
| MIA | SON | 16 | 0 | 172 | 2 | 1.163% | 4.140% | 2 | 0 | 2 | 1.163% | 4.140% | 0 | 2.185% |
| MIA | SON | 16 | 1 | 280 | 0 | 0.000% | 1.353% | 0 | 0 | 0 | 0.000% | 1.353% | 0 | 1.353% |
| MIA | SON | 17 | 0 | 171 | 1 | 0.585% | 3.238% | 1 | 0 | 1 | 0.585% | 3.238% | 0 | 2.197% |
| MIA | SON | 17 | 1 | 281 | 0 | 0.000% | 1.349% | 0 | 0 | 0 | 0.000% | 1.349% | 0 | 1.349% |
| MIA | SON | 18 | 0 | 171 | 1 | 0.585% | 3.238% | 1 | 0 | 1 | 0.585% | 3.238% | 0 | 2.197% |
| MIA | SON | 18 | 1 | 281 | 0 | 0.000% | 1.349% | 0 | 0 | 0 | 0.000% | 1.349% | 0 | 1.349% |
| MIA | SON | 19 | 0 | 171 | 1 | 0.585% | 3.238% | 1 | 0 | 1 | 0.585% | 3.238% | 0 | 2.197% |
| MIA | SON | 19 | 1 | 281 | 0 | 0.000% | 1.349% | 0 | 0 | 0 | 0.000% | 1.349% | 0 | 1.349% |
| MIA | SON | 20 | 0 | 171 | 1 | 0.585% | 3.238% | 1 | 0 | 1 | 0.585% | 3.238% | 0 | 2.197% |
| MIA | SON | 20 | 1 | 281 | 0 | 0.000% | 1.349% | 0 | 0 | 0 | 0.000% | 1.349% | 0 | 1.349% |
| MIA | SON | 21 | 0 | 170 | 0 | 0.000% | 2.210% | 0 | 0 | 0 | 0.000% | 2.210% | 0 | 2.210% |
| MIA | SON | 21 | 1 | 282 | 0 | 0.000% | 1.344% | 0 | 0 | 0 | 0.000% | 1.344% | 0 | 1.344% |
| MIA | SON | 22 | 0 | 170 | 0 | 0.000% | 2.210% | 0 | 0 | 0 | 0.000% | 2.210% | 0 | 2.210% |
| MIA | SON | 22 | 1 | 282 | 0 | 0.000% | 1.344% | 0 | 0 | 0 | 0.000% | 1.344% | 0 | 1.344% |
| MIA | SON | 23 | 0 | 170 | 0 | 0.000% | 2.210% | 0 | 0 | 0 | 0.000% | 2.210% | 0 | 2.210% |
| MIA | SON | 23 | 1 | 282 | 0 | 0.000% | 1.344% | 0 | 0 | 0 | 0.000% | 1.344% | 0 | 1.344% |
| NYC | DJF | 00 | 0 | 209 | 179 | 85.646% | 89.757% | 179 | 0 | 179 | 85.646% | 89.757% | 0 | 1.805% |
| NYC | DJF | 00 | 1 | 212 | 181 | 85.377% | 89.503% | 181 | 0 | 191 | 90.094% | 93.430% | 0 | 1.780% |
| NYC | DJF | 01 | 0 | 205 | 175 | 85.366% | 89.553% | 175 | 0 | 175 | 85.366% | 89.553% | 0 | 1.839% |
| NYC | DJF | 01 | 1 | 216 | 179 | 82.870% | 87.309% | 179 | 0 | 192 | 88.889% | 92.419% | 0 | 1.747% |
| NYC | DJF | 02 | 0 | 205 | 173 | 84.390% | 88.721% | 173 | 0 | 173 | 84.390% | 88.721% | 0 | 1.839% |
| NYC | DJF | 02 | 1 | 216 | 178 | 82.407% | 86.906% | 178 | 0 | 190 | 87.963% | 91.652% | 0 | 1.747% |
| NYC | DJF | 03 | 0 | 206 | 171 | 83.010% | 87.522% | 171 | 0 | 171 | 83.010% | 87.522% | 0 | 1.831% |
| NYC | DJF | 03 | 1 | 215 | 179 | 83.256% | 87.653% | 179 | 0 | 189 | 87.907% | 91.612% | 0 | 1.755% |
| NYC | DJF | 04 | 0 | 204 | 168 | 82.353% | 86.972% | 168 | 0 | 168 | 82.353% | 86.972% | 0 | 1.848% |
| NYC | DJF | 04 | 1 | 217 | 178 | 82.028% | 86.565% | 178 | 0 | 189 | 87.097% | 90.920% | 0 | 1.739% |
| NYC | DJF | 05 | 0 | 201 | 164 | 81.592% | 86.340% | 164 | 0 | 164 | 81.592% | 86.340% | 0 | 1.875% |
| NYC | DJF | 05 | 1 | 220 | 179 | 81.364% | 85.955% | 179 | 0 | 189 | 85.909% | 89.892% | 0 | 1.716% |
| NYC | DJF | 06 | 0 | 196 | 158 | 80.612% | 85.536% | 158 | 0 | 158 | 80.612% | 85.536% | 0 | 1.922% |
| NYC | DJF | 06 | 1 | 225 | 182 | 80.889% | 85.491% | 182 | 0 | 191 | 84.889% | 88.980% | 0 | 1.679% |
| NYC | DJF | 07 | 0 | 207 | 168 | 81.159% | 85.900% | 168 | 0 | 168 | 81.159% | 85.900% | 0 | 1.822% |
| NYC | DJF | 07 | 1 | 214 | 169 | 78.972% | 83.897% | 169 | 0 | 180 | 84.112% | 88.402% | 0 | 1.763% |
| NYC | DJF | 08 | 0 | 202 | 161 | 79.703% | 84.671% | 161 | 0 | 161 | 79.703% | 84.671% | 0 | 1.866% |
| NYC | DJF | 08 | 1 | 219 | 171 | 78.082% | 83.051% | 171 | 0 | 183 | 83.562% | 87.883% | 0 | 1.724% |
| NYC | DJF | 09 | 0 | 200 | 159 | 79.500% | 84.514% | 159 | 0 | 159 | 79.500% | 84.514% | 0 | 1.885% |
| NYC | DJF | 09 | 1 | 221 | 166 | 75.113% | 80.352% | 166 | 0 | 183 | 82.805% | 87.209% | 0 | 1.709% |
| NYC | DJF | 10 | 0 | 216 | 169 | 78.241% | 83.224% | 169 | 0 | 169 | 78.241% | 83.224% | 0 | 1.747% |
| NYC | DJF | 10 | 1 | 205 | 145 | 70.732% | 76.533% | 145 | 0 | 162 | 79.024% | 84.038% | 0 | 1.839% |
| NYC | DJF | 11 | 0 | 200 | 142 | 71.000% | 76.846% | 142 | 0 | 142 | 71.000% | 76.846% | 0 | 1.885% |
| NYC | DJF | 11 | 1 | 221 | 125 | 56.561% | 62.929% | 125 | 0 | 162 | 73.303% | 78.701% | 0 | 1.709% |
| NYC | DJF | 12 | 0 | 217 | 127 | 58.525% | 64.877% | 127 | 0 | 127 | 58.525% | 64.877% | 0 | 1.739% |
| NYC | DJF | 12 | 1 | 204 | 72 | 35.294% | 42.068% | 72 | 0 | 110 | 53.922% | 60.626% | 0 | 1.848% |
| NYC | DJF | 13 | 0 | 193 | 72 | 37.306% | 44.314% | 72 | 0 | 72 | 37.306% | 44.314% | 0 | 1.952% |
| NYC | DJF | 13 | 1 | 228 | 45 | 19.737% | 25.386% | 45 | 0 | 91 | 39.912% | 46.385% | 0 | 1.657% |
| NYC | DJF | 14 | 0 | 207 | 47 | 22.705% | 28.879% | 47 | 0 | 47 | 22.705% | 28.879% | 0 | 1.822% |
| NYC | DJF | 14 | 1 | 214 | 21 | 9.813% | 14.535% | 21 | 0 | 45 | 21.028% | 26.974% | 0 | 1.763% |
| NYC | DJF | 15 | 0 | 197 | 26 | 13.198% | 18.636% | 26 | 0 | 26 | 13.198% | 18.636% | 0 | 1.913% |
| NYC | DJF | 15 | 1 | 224 | 20 | 8.929% | 13.388% | 20 | 0 | 35 | 15.625% | 20.955% | 0 | 1.686% |
| NYC | DJF | 16 | 0 | 199 | 26 | 13.065% | 18.455% | 26 | 0 | 26 | 13.065% | 18.455% | 0 | 1.894% |
| NYC | DJF | 16 | 1 | 222 | 14 | 6.306% | 10.306% | 14 | 0 | 31 | 13.964% | 19.139% | 0 | 1.701% |
| NYC | DJF | 17 | 0 | 203 | 25 | 12.315% | 17.548% | 25 | 0 | 25 | 12.315% | 17.548% | 0 | 1.857% |
| NYC | DJF | 17 | 1 | 218 | 12 | 5.505% | 9.374% | 12 | 0 | 26 | 11.927% | 16.901% | 0 | 1.732% |
| NYC | DJF | 18 | 0 | 204 | 22 | 10.784% | 15.788% | 22 | 0 | 22 | 10.784% | 15.788% | 0 | 1.848% |
| NYC | DJF | 18 | 1 | 217 | 12 | 5.530% | 9.416% | 12 | 0 | 23 | 10.599% | 15.402% | 0 | 1.739% |
| NYC | DJF | 19 | 0 | 202 | 17 | 8.416% | 13.063% | 17 | 0 | 17 | 8.416% | 13.063% | 0 | 1.866% |
| NYC | DJF | 19 | 1 | 219 | 11 | 5.023% | 8.769% | 11 | 0 | 21 | 9.589% | 14.214% | 0 | 1.724% |
| NYC | DJF | 20 | 0 | 204 | 14 | 6.863% | 11.188% | 14 | 0 | 14 | 6.863% | 11.188% | 0 | 1.848% |
| NYC | DJF | 20 | 1 | 217 | 10 | 4.608% | 8.274% | 10 | 0 | 15 | 6.912% | 11.090% | 0 | 1.739% |
| NYC | DJF | 21 | 0 | 205 | 14 | 6.829% | 11.135% | 14 | 0 | 14 | 6.829% | 11.135% | 0 | 1.839% |
| NYC | DJF | 21 | 1 | 216 | 6 | 2.778% | 5.927% | 6 | 0 | 12 | 5.556% | 9.458% | 0 | 1.747% |
| NYC | DJF | 22 | 0 | 205 | 12 | 5.854% | 9.951% | 12 | 0 | 12 | 5.854% | 9.951% | 0 | 1.839% |
| NYC | DJF | 22 | 1 | 216 | 0 | 0.000% | 1.747% | 0 | 0 | 9 | 4.167% | 7.728% | 0 | 1.747% |
| NYC | DJF | 23 | 0 | 205 | 0 | 0.000% | 1.839% | 0 | 0 | 0 | 0.000% | 1.839% | 0 | 1.839% |
| NYC | DJF | 23 | 1 | 216 | 0 | 0.000% | 1.747% | 0 | 0 | 0 | 0.000% | 1.747% | 0 | 1.747% |
| NYC | JJA | 00 | 0 | 218 | 214 | 98.165% | 99.284% | 214 | 0 | 214 | 98.165% | 99.284% | 0 | 1.732% |
| NYC | JJA | 00 | 1 | 231 | 221 | 95.671% | 97.632% | 221 | 0 | 225 | 97.403% | 98.804% | 0 | 1.636% |
| NYC | JJA | 01 | 0 | 219 | 215 | 98.174% | 99.287% | 215 | 0 | 215 | 98.174% | 99.287% | 0 | 1.724% |
| NYC | JJA | 01 | 1 | 230 | 218 | 94.783% | 96.991% | 218 | 0 | 223 | 96.957% | 98.518% | 0 | 1.643% |
| NYC | JJA | 02 | 0 | 224 | 220 | 98.214% | 99.303% | 220 | 0 | 220 | 98.214% | 99.303% | 0 | 1.686% |
| NYC | JJA | 02 | 1 | 225 | 213 | 94.667% | 96.923% | 213 | 0 | 218 | 96.889% | 98.485% | 0 | 1.679% |
| NYC | JJA | 03 | 0 | 224 | 220 | 98.214% | 99.303% | 220 | 0 | 220 | 98.214% | 99.303% | 0 | 1.686% |
| NYC | JJA | 03 | 1 | 225 | 213 | 94.667% | 96.923% | 213 | 0 | 218 | 96.889% | 98.485% | 0 | 1.679% |
| NYC | JJA | 04 | 0 | 226 | 221 | 97.788% | 99.051% | 221 | 0 | 221 | 97.788% | 99.051% | 0 | 1.671% |
| NYC | JJA | 04 | 1 | 223 | 212 | 95.067% | 97.224% | 212 | 0 | 216 | 96.861% | 98.471% | 0 | 1.693% |
| NYC | JJA | 05 | 0 | 222 | 217 | 97.748% | 99.034% | 217 | 0 | 217 | 97.748% | 99.034% | 0 | 1.701% |
| NYC | JJA | 05 | 1 | 227 | 215 | 94.714% | 96.950% | 215 | 0 | 220 | 96.916% | 98.498% | 0 | 1.664% |
| NYC | JJA | 06 | 0 | 217 | 212 | 97.696% | 99.012% | 212 | 0 | 212 | 97.696% | 99.012% | 0 | 1.739% |
| NYC | JJA | 06 | 1 | 232 | 220 | 94.828% | 97.017% | 220 | 0 | 225 | 96.983% | 98.531% | 0 | 1.629% |
| NYC | JJA | 07 | 0 | 223 | 216 | 96.861% | 98.471% | 216 | 0 | 216 | 96.861% | 98.471% | 0 | 1.693% |
| NYC | JJA | 07 | 1 | 226 | 216 | 95.575% | 97.579% | 216 | 0 | 219 | 96.903% | 98.492% | 0 | 1.671% |
| NYC | JJA | 08 | 0 | 205 | 198 | 96.585% | 98.336% | 198 | 0 | 198 | 96.585% | 98.336% | 0 | 1.839% |
| NYC | JJA | 08 | 1 | 244 | 231 | 94.672% | 96.860% | 231 | 0 | 237 | 97.131% | 98.604% | 0 | 1.550% |
| NYC | JJA | 09 | 0 | 215 | 204 | 94.884% | 97.119% | 204 | 0 | 204 | 94.884% | 97.119% | 0 | 1.755% |
| NYC | JJA | 09 | 1 | 234 | 216 | 92.308% | 95.079% | 216 | 0 | 224 | 95.726% | 97.662% | 0 | 1.615% |
| NYC | JJA | 10 | 0 | 221 | 198 | 89.593% | 92.965% | 198 | 0 | 198 | 89.593% | 92.965% | 0 | 1.709% |
| NYC | JJA | 10 | 1 | 228 | 182 | 79.825% | 84.520% | 182 | 0 | 204 | 89.474% | 92.824% | 0 | 1.657% |
| NYC | JJA | 11 | 0 | 230 | 164 | 71.304% | 76.763% | 164 | 0 | 164 | 71.304% | 76.763% | 0 | 1.643% |
| NYC | JJA | 11 | 1 | 219 | 101 | 46.119% | 52.731% | 101 | 0 | 158 | 72.146% | 77.662% | 0 | 1.724% |
| NYC | JJA | 12 | 0 | 223 | 90 | 40.359% | 46.909% | 90 | 0 | 90 | 40.359% | 46.909% | 0 | 1.693% |
| NYC | JJA | 12 | 1 | 226 | 51 | 22.566% | 28.448% | 51 | 0 | 99 | 43.805% | 50.324% | 0 | 1.671% |
| NYC | JJA | 13 | 0 | 235 | 62 | 26.383% | 32.365% | 62 | 0 | 62 | 26.383% | 32.365% | 0 | 1.608% |
| NYC | JJA | 13 | 1 | 214 | 23 | 10.748% | 15.611% | 23 | 0 | 53 | 24.766% | 30.961% | 0 | 1.763% |
| NYC | JJA | 14 | 0 | 247 | 41 | 16.599% | 21.743% | 41 | 0 | 41 | 16.599% | 21.743% | 0 | 1.531% |
| NYC | JJA | 14 | 1 | 202 | 5 | 2.475% | 5.663% | 5 | 0 | 19 | 9.406% | 14.223% | 0 | 1.866% |
| NYC | JJA | 15 | 0 | 233 | 12 | 5.150% | 8.785% | 12 | 0 | 12 | 5.150% | 8.785% | 0 | 1.622% |
| NYC | JJA | 15 | 1 | 216 | 1 | 0.463% | 2.575% | 1 | 0 | 13 | 6.019% | 10.023% | 0 | 1.747% |
| NYC | JJA | 16 | 0 | 233 | 1 | 0.429% | 2.391% | 1 | 0 | 1 | 0.429% | 2.391% | 0 | 1.622% |
| NYC | JJA | 16 | 1 | 216 | 0 | 0.000% | 1.747% | 0 | 0 | 5 | 2.315% | 5.303% | 0 | 1.747% |
| NYC | JJA | 17 | 0 | 238 | 1 | 0.420% | 2.341% | 1 | 0 | 1 | 0.420% | 2.341% | 0 | 1.588% |
| NYC | JJA | 17 | 1 | 211 | 0 | 0.000% | 1.788% | 0 | 0 | 0 | 0.000% | 1.788% | 0 | 1.788% |
| NYC | JJA | 18 | 0 | 238 | 1 | 0.420% | 2.341% | 1 | 0 | 1 | 0.420% | 2.341% | 0 | 1.588% |
| NYC | JJA | 18 | 1 | 211 | 0 | 0.000% | 1.788% | 0 | 0 | 0 | 0.000% | 1.788% | 0 | 1.788% |
| NYC | JJA | 19 | 0 | 238 | 1 | 0.420% | 2.341% | 1 | 0 | 1 | 0.420% | 2.341% | 0 | 1.588% |
| NYC | JJA | 19 | 1 | 211 | 0 | 0.000% | 1.788% | 0 | 0 | 0 | 0.000% | 1.788% | 0 | 1.788% |
| NYC | JJA | 20 | 0 | 238 | 1 | 0.420% | 2.341% | 1 | 0 | 1 | 0.420% | 2.341% | 0 | 1.588% |
| NYC | JJA | 20 | 1 | 211 | 0 | 0.000% | 1.788% | 0 | 0 | 0 | 0.000% | 1.788% | 0 | 1.788% |
| NYC | JJA | 21 | 0 | 238 | 1 | 0.420% | 2.341% | 1 | 0 | 1 | 0.420% | 2.341% | 0 | 1.588% |
| NYC | JJA | 21 | 1 | 211 | 0 | 0.000% | 1.788% | 0 | 0 | 0 | 0.000% | 1.788% | 0 | 1.788% |
| NYC | JJA | 22 | 0 | 237 | 0 | 0.000% | 1.595% | 0 | 0 | 0 | 0.000% | 1.595% | 0 | 1.595% |
| NYC | JJA | 22 | 1 | 212 | 0 | 0.000% | 1.780% | 0 | 0 | 0 | 0.000% | 1.780% | 0 | 1.780% |
| NYC | JJA | 23 | 0 | 237 | 0 | 0.000% | 1.595% | 0 | 0 | 0 | 0.000% | 1.595% | 0 | 1.595% |
| NYC | JJA | 23 | 1 | 212 | 0 | 0.000% | 1.780% | 0 | 0 | 0 | 0.000% | 1.780% | 0 | 1.780% |
| NYC | MAM | 00 | 0 | 209 | 192 | 91.866% | 94.860% | 192 | 0 | 192 | 91.866% | 94.860% | 0 | 1.805% |
| NYC | MAM | 00 | 1 | 222 | 197 | 88.739% | 92.255% | 197 | 0 | 202 | 90.991% | 94.092% | 0 | 1.701% |
| NYC | MAM | 01 | 0 | 216 | 199 | 92.130% | 95.028% | 199 | 0 | 199 | 92.130% | 95.028% | 0 | 1.747% |
| NYC | MAM | 01 | 1 | 215 | 187 | 86.977% | 90.834% | 187 | 0 | 194 | 90.233% | 93.523% | 0 | 1.755% |
| NYC | MAM | 02 | 0 | 214 | 196 | 91.589% | 94.613% | 196 | 0 | 196 | 91.589% | 94.613% | 0 | 1.763% |
| NYC | MAM | 02 | 1 | 217 | 190 | 87.558% | 91.306% | 190 | 0 | 196 | 90.323% | 93.583% | 0 | 1.739% |
| NYC | MAM | 03 | 0 | 217 | 198 | 91.244% | 94.323% | 198 | 0 | 198 | 91.244% | 94.323% | 0 | 1.739% |
| NYC | MAM | 03 | 1 | 214 | 187 | 87.383% | 91.182% | 187 | 0 | 193 | 90.187% | 93.492% | 0 | 1.763% |
| NYC | MAM | 04 | 0 | 211 | 192 | 90.995% | 94.159% | 192 | 0 | 192 | 90.995% | 94.159% | 0 | 1.788% |
| NYC | MAM | 04 | 1 | 220 | 193 | 87.727% | 91.427% | 193 | 0 | 199 | 90.455% | 93.672% | 0 | 1.716% |
| NYC | MAM | 05 | 0 | 219 | 199 | 90.868% | 94.010% | 199 | 0 | 199 | 90.868% | 94.010% | 0 | 1.724% |
| NYC | MAM | 05 | 1 | 212 | 186 | 87.736% | 91.492% | 186 | 0 | 191 | 90.094% | 93.430% | 0 | 1.780% |
| NYC | MAM | 06 | 0 | 225 | 205 | 91.111% | 94.172% | 205 | 0 | 205 | 91.111% | 94.172% | 0 | 1.679% |
| NYC | MAM | 06 | 1 | 206 | 179 | 86.893% | 90.834% | 179 | 0 | 184 | 89.320% | 92.841% | 0 | 1.831% |
| NYC | MAM | 07 | 0 | 210 | 188 | 89.524% | 92.979% | 188 | 0 | 188 | 89.524% | 92.979% | 0 | 1.796% |
| NYC | MAM | 07 | 1 | 221 | 193 | 87.330% | 91.087% | 193 | 0 | 199 | 90.045% | 93.334% | 0 | 1.709% |
| NYC | MAM | 08 | 0 | 218 | 193 | 88.532% | 92.111% | 193 | 0 | 193 | 88.532% | 92.111% | 0 | 1.732% |
| NYC | MAM | 08 | 1 | 213 | 182 | 85.446% | 89.554% | 182 | 0 | 190 | 89.202% | 92.696% | 0 | 1.772% |
| NYC | MAM | 09 | 0 | 201 | 170 | 84.577% | 88.917% | 170 | 0 | 170 | 84.577% | 88.917% | 0 | 1.875% |
| NYC | MAM | 09 | 1 | 230 | 197 | 85.652% | 89.598% | 197 | 0 | 207 | 90.000% | 93.244% | 0 | 1.643% |
| NYC | MAM | 10 | 0 | 231 | 190 | 82.251% | 86.639% | 190 | 0 | 190 | 82.251% | 86.639% | 0 | 1.636% |
| NYC | MAM | 10 | 1 | 200 | 151 | 75.500% | 80.943% | 151 | 0 | 169 | 84.500% | 88.860% | 0 | 1.885% |
| NYC | MAM | 11 | 0 | 227 | 163 | 71.806% | 77.259% | 163 | 0 | 163 | 71.806% | 77.259% | 0 | 1.664% |
| NYC | MAM | 11 | 1 | 204 | 127 | 62.255% | 68.622% | 127 | 0 | 157 | 76.961% | 82.209% | 0 | 1.848% |
| NYC | MAM | 12 | 0 | 222 | 116 | 52.252% | 58.728% | 116 | 0 | 116 | 52.252% | 58.728% | 0 | 1.701% |
| NYC | MAM | 12 | 1 | 209 | 72 | 34.450% | 41.121% | 72 | 0 | 115 | 55.024% | 61.617% | 0 | 1.805% |
| NYC | MAM | 13 | 0 | 234 | 80 | 34.188% | 40.477% | 80 | 0 | 80 | 34.188% | 40.477% | 0 | 1.615% |
| NYC | MAM | 13 | 1 | 197 | 35 | 17.766% | 23.705% | 35 | 0 | 68 | 34.518% | 41.396% | 0 | 1.913% |
| NYC | MAM | 14 | 0 | 228 | 35 | 15.351% | 20.601% | 35 | 0 | 35 | 15.351% | 20.601% | 0 | 1.657% |
| NYC | MAM | 14 | 1 | 203 | 11 | 5.419% | 9.441% | 11 | 0 | 30 | 14.778% | 20.313% | 0 | 1.857% |
| NYC | MAM | 15 | 0 | 227 | 14 | 6.167% | 10.085% | 14 | 0 | 14 | 6.167% | 10.085% | 0 | 1.664% |
| NYC | MAM | 15 | 1 | 204 | 5 | 2.451% | 5.608% | 5 | 0 | 10 | 4.902% | 8.787% | 0 | 1.848% |
| NYC | MAM | 16 | 0 | 222 | 5 | 2.252% | 5.163% | 5 | 0 | 5 | 2.252% | 5.163% | 0 | 1.701% |
| NYC | MAM | 16 | 1 | 209 | 4 | 1.914% | 4.817% | 4 | 0 | 10 | 4.785% | 8.582% | 0 | 1.805% |
| NYC | MAM | 17 | 0 | 226 | 6 | 2.655% | 5.670% | 6 | 0 | 6 | 2.655% | 5.670% | 0 | 1.671% |
| NYC | MAM | 17 | 1 | 205 | 2 | 0.976% | 3.487% | 2 | 0 | 5 | 2.439% | 5.582% | 0 | 1.839% |
| NYC | MAM | 18 | 0 | 224 | 3 | 1.339% | 3.863% | 3 | 0 | 3 | 1.339% | 3.863% | 0 | 1.686% |
| NYC | MAM | 18 | 1 | 207 | 5 | 2.415% | 5.529% | 5 | 0 | 7 | 3.382% | 6.814% | 0 | 1.822% |
| NYC | MAM | 19 | 0 | 225 | 2 | 0.889% | 3.182% | 2 | 0 | 2 | 0.889% | 3.182% | 0 | 1.679% |
| NYC | MAM | 19 | 1 | 206 | 4 | 1.942% | 4.885% | 4 | 0 | 5 | 2.427% | 5.555% | 0 | 1.831% |
| NYC | MAM | 20 | 0 | 229 | 5 | 2.183% | 5.008% | 5 | 0 | 5 | 2.183% | 5.008% | 0 | 1.650% |
| NYC | MAM | 20 | 1 | 202 | 1 | 0.495% | 2.750% | 1 | 0 | 1 | 0.495% | 2.750% | 0 | 1.866% |
| NYC | MAM | 21 | 0 | 226 | 2 | 0.885% | 3.169% | 2 | 0 | 2 | 0.885% | 3.169% | 0 | 1.671% |
| NYC | MAM | 21 | 1 | 205 | 1 | 0.488% | 2.711% | 1 | 0 | 2 | 0.976% | 3.487% | 0 | 1.839% |
| NYC | MAM | 22 | 0 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| NYC | MAM | 22 | 1 | 207 | 1 | 0.483% | 2.685% | 1 | 0 | 3 | 1.449% | 4.174% | 0 | 1.822% |
| NYC | MAM | 23 | 0 | 226 | 0 | 0.000% | 1.671% | 0 | 0 | 0 | 0.000% | 1.671% | 0 | 1.671% |
| NYC | MAM | 23 | 1 | 205 | 0 | 0.000% | 1.839% | 0 | 0 | 0 | 0.000% | 1.839% | 0 | 1.839% |
| NYC | SON | 00 | 0 | 207 | 191 | 92.271% | 95.186% | 191 | 0 | 191 | 92.271% | 95.186% | 0 | 1.822% |
| NYC | SON | 00 | 1 | 232 | 209 | 90.086% | 93.303% | 209 | 0 | 215 | 92.672% | 95.375% | 0 | 1.629% |
| NYC | SON | 01 | 0 | 211 | 193 | 91.469% | 94.536% | 193 | 0 | 193 | 91.469% | 94.536% | 0 | 1.788% |
| NYC | SON | 01 | 1 | 228 | 204 | 89.474% | 92.824% | 204 | 0 | 208 | 91.228% | 94.250% | 0 | 1.657% |
| NYC | SON | 02 | 0 | 212 | 194 | 91.509% | 94.562% | 194 | 0 | 194 | 91.509% | 94.562% | 0 | 1.780% |
| NYC | SON | 02 | 1 | 227 | 203 | 89.427% | 92.792% | 203 | 0 | 207 | 91.189% | 94.224% | 0 | 1.664% |
| NYC | SON | 03 | 0 | 217 | 198 | 91.244% | 94.323% | 198 | 0 | 198 | 91.244% | 94.323% | 0 | 1.739% |
| NYC | SON | 03 | 1 | 222 | 199 | 89.640% | 92.997% | 199 | 0 | 202 | 90.991% | 94.092% | 0 | 1.701% |
| NYC | SON | 04 | 0 | 213 | 194 | 91.080% | 94.215% | 194 | 0 | 194 | 91.080% | 94.215% | 0 | 1.772% |
| NYC | SON | 04 | 1 | 226 | 203 | 89.823% | 93.122% | 203 | 0 | 206 | 91.150% | 94.198% | 0 | 1.671% |
| NYC | SON | 05 | 0 | 216 | 197 | 91.204% | 94.296% | 197 | 0 | 197 | 91.204% | 94.296% | 0 | 1.747% |
| NYC | SON | 05 | 1 | 223 | 199 | 89.238% | 92.660% | 199 | 0 | 203 | 91.031% | 94.119% | 0 | 1.693% |
| NYC | SON | 06 | 0 | 215 | 195 | 90.698% | 93.897% | 195 | 0 | 195 | 90.698% | 93.897% | 0 | 1.755% |
| NYC | SON | 06 | 1 | 224 | 199 | 88.839% | 92.325% | 199 | 0 | 203 | 90.625% | 93.786% | 0 | 1.686% |
| NYC | SON | 07 | 0 | 206 | 186 | 90.291% | 93.627% | 186 | 0 | 186 | 90.291% | 93.627% | 0 | 1.831% |
| NYC | SON | 07 | 1 | 233 | 208 | 89.270% | 92.626% | 208 | 0 | 212 | 90.987% | 94.029% | 0 | 1.622% |
| NYC | SON | 08 | 0 | 208 | 187 | 89.904% | 93.301% | 187 | 0 | 187 | 89.904% | 93.301% | 0 | 1.813% |
| NYC | SON | 08 | 1 | 231 | 202 | 87.446% | 91.115% | 202 | 0 | 208 | 90.043% | 93.273% | 0 | 1.636% |
| NYC | SON | 09 | 0 | 218 | 195 | 89.450% | 92.866% | 195 | 0 | 195 | 89.450% | 92.866% | 0 | 1.732% |
| NYC | SON | 09 | 1 | 221 | 185 | 83.710% | 87.995% | 185 | 0 | 193 | 87.330% | 91.087% | 0 | 1.709% |
| NYC | SON | 10 | 0 | 215 | 189 | 87.907% | 91.612% | 189 | 0 | 189 | 87.907% | 91.612% | 0 | 1.755% |
| NYC | SON | 10 | 1 | 224 | 170 | 75.893% | 81.027% | 170 | 0 | 189 | 84.375% | 88.546% | 0 | 1.686% |
| NYC | SON | 11 | 0 | 229 | 177 | 77.293% | 82.242% | 177 | 0 | 177 | 77.293% | 82.242% | 0 | 1.650% |
| NYC | SON | 11 | 1 | 210 | 99 | 47.143% | 53.885% | 99 | 0 | 147 | 70.000% | 75.793% | 0 | 1.796% |
| NYC | SON | 12 | 0 | 203 | 104 | 51.232% | 58.021% | 104 | 0 | 104 | 51.232% | 58.021% | 0 | 1.857% |
| NYC | SON | 12 | 1 | 236 | 55 | 23.305% | 29.100% | 55 | 0 | 121 | 51.271% | 57.577% | 0 | 1.602% |
| NYC | SON | 13 | 0 | 212 | 49 | 23.113% | 29.236% | 49 | 0 | 49 | 23.113% | 29.236% | 0 | 1.780% |
| NYC | SON | 13 | 1 | 227 | 21 | 9.251% | 13.728% | 21 | 0 | 58 | 25.551% | 31.599% | 0 | 1.664% |
| NYC | SON | 14 | 0 | 210 | 16 | 7.619% | 12.017% | 16 | 0 | 16 | 7.619% | 12.017% | 0 | 1.796% |
| NYC | SON | 14 | 1 | 229 | 7 | 3.057% | 6.174% | 7 | 0 | 21 | 9.170% | 13.612% | 0 | 1.650% |
| NYC | SON | 15 | 0 | 209 | 9 | 4.306% | 7.980% | 9 | 0 | 9 | 4.306% | 7.980% | 0 | 1.805% |
| NYC | SON | 15 | 1 | 230 | 5 | 2.174% | 4.987% | 5 | 0 | 15 | 6.522% | 10.480% | 0 | 1.643% |
| NYC | SON | 16 | 0 | 212 | 10 | 4.717% | 8.464% | 10 | 0 | 10 | 4.717% | 8.464% | 0 | 1.780% |
| NYC | SON | 16 | 1 | 227 | 3 | 1.322% | 3.813% | 3 | 0 | 11 | 4.846% | 8.467% | 0 | 1.664% |
| NYC | SON | 17 | 0 | 211 | 7 | 3.318% | 6.688% | 7 | 0 | 7 | 3.318% | 6.688% | 0 | 1.788% |
| NYC | SON | 17 | 1 | 228 | 2 | 0.877% | 3.141% | 2 | 0 | 9 | 3.947% | 7.330% | 0 | 1.657% |
| NYC | SON | 18 | 0 | 213 | 6 | 2.817% | 6.008% | 6 | 0 | 6 | 2.817% | 6.008% | 0 | 1.772% |
| NYC | SON | 18 | 1 | 226 | 2 | 0.885% | 3.169% | 2 | 0 | 7 | 3.097% | 6.254% | 0 | 1.671% |
| NYC | SON | 19 | 0 | 212 | 4 | 1.887% | 4.750% | 4 | 0 | 4 | 1.887% | 4.750% | 0 | 1.780% |
| NYC | SON | 19 | 1 | 227 | 2 | 0.881% | 3.155% | 2 | 0 | 7 | 3.084% | 6.227% | 0 | 1.664% |
| NYC | SON | 20 | 0 | 214 | 5 | 2.336% | 5.352% | 5 | 0 | 5 | 2.336% | 5.352% | 0 | 1.763% |
| NYC | SON | 20 | 1 | 225 | 1 | 0.444% | 2.474% | 1 | 0 | 5 | 2.222% | 5.096% | 0 | 1.679% |
| NYC | SON | 21 | 0 | 214 | 2 | 0.935% | 3.343% | 2 | 0 | 2 | 0.935% | 3.343% | 0 | 1.763% |
| NYC | SON | 21 | 1 | 225 | 2 | 0.889% | 3.182% | 2 | 0 | 4 | 1.778% | 4.481% | 0 | 1.679% |
| NYC | SON | 22 | 0 | 216 | 2 | 0.926% | 3.313% | 2 | 0 | 2 | 0.926% | 3.313% | 0 | 1.747% |
| NYC | SON | 22 | 1 | 223 | 0 | 0.000% | 1.693% | 0 | 0 | 0 | 0.000% | 1.693% | 0 | 1.693% |
| NYC | SON | 23 | 0 | 215 | 0 | 0.000% | 1.755% | 0 | 0 | 0 | 0.000% | 1.755% | 0 | 1.755% |
| NYC | SON | 23 | 1 | 224 | 0 | 0.000% | 1.686% | 0 | 0 | 0 | 0.000% | 1.686% | 0 | 1.686% |
| SFO | DJF | 00 | 0 | 141 | 131 | 92.908% | 96.102% | 131 | 0 | 131 | 92.908% | 96.102% | 0 | 2.652% |
| SFO | DJF | 00 | 1 | 309 | 294 | 95.146% | 97.036% | 294 | 0 | 299 | 96.764% | 98.233% | 0 | 1.228% |
| SFO | DJF | 01 | 0 | 138 | 125 | 90.580% | 94.412% | 125 | 0 | 125 | 90.580% | 94.412% | 0 | 2.708% |
| SFO | DJF | 01 | 1 | 312 | 293 | 93.910% | 96.067% | 293 | 0 | 300 | 96.154% | 97.786% | 0 | 1.216% |
| SFO | DJF | 02 | 0 | 134 | 120 | 89.552% | 93.674% | 120 | 0 | 120 | 89.552% | 93.674% | 0 | 2.787% |
| SFO | DJF | 02 | 1 | 316 | 295 | 93.354% | 95.613% | 295 | 0 | 303 | 95.886% | 97.580% | 0 | 1.201% |
| SFO | DJF | 03 | 0 | 137 | 123 | 89.781% | 93.815% | 123 | 0 | 123 | 89.781% | 93.815% | 0 | 2.728% |
| SFO | DJF | 03 | 1 | 313 | 292 | 93.291% | 95.570% | 292 | 0 | 300 | 95.847% | 97.557% | 0 | 1.212% |
| SFO | DJF | 04 | 0 | 142 | 126 | 88.732% | 92.944% | 126 | 0 | 126 | 88.732% | 92.944% | 0 | 2.634% |
| SFO | DJF | 04 | 1 | 308 | 287 | 93.182% | 95.498% | 287 | 0 | 295 | 95.779% | 97.517% | 0 | 1.232% |
| SFO | DJF | 05 | 0 | 148 | 132 | 89.189% | 93.235% | 132 | 0 | 132 | 89.189% | 93.235% | 0 | 2.530% |
| SFO | DJF | 05 | 1 | 302 | 280 | 92.715% | 95.140% | 280 | 0 | 288 | 95.364% | 97.219% | 0 | 1.256% |
| SFO | DJF | 06 | 0 | 152 | 136 | 89.474% | 93.416% | 136 | 0 | 136 | 89.474% | 93.416% | 0 | 2.465% |
| SFO | DJF | 06 | 1 | 298 | 276 | 92.617% | 95.074% | 276 | 0 | 284 | 95.302% | 97.181% | 0 | 1.273% |
| SFO | DJF | 07 | 0 | 149 | 132 | 88.591% | 92.753% | 132 | 0 | 132 | 88.591% | 92.753% | 0 | 2.513% |
| SFO | DJF | 07 | 1 | 301 | 279 | 92.691% | 95.124% | 279 | 0 | 287 | 95.349% | 97.209% | 0 | 1.260% |
| SFO | DJF | 08 | 0 | 169 | 150 | 88.757% | 92.683% | 150 | 0 | 150 | 88.757% | 92.683% | 0 | 2.223% |
| SFO | DJF | 08 | 1 | 281 | 259 | 92.171% | 94.773% | 259 | 0 | 267 | 95.018% | 97.009% | 0 | 1.349% |
| SFO | DJF | 09 | 0 | 170 | 147 | 86.471% | 90.813% | 147 | 0 | 147 | 86.471% | 90.813% | 0 | 2.210% |
| SFO | DJF | 09 | 1 | 280 | 255 | 91.071% | 93.879% | 255 | 0 | 264 | 94.286% | 96.452% | 0 | 1.353% |
| SFO | DJF | 10 | 0 | 188 | 156 | 82.979% | 87.677% | 156 | 0 | 156 | 82.979% | 87.677% | 0 | 2.002% |
| SFO | DJF | 10 | 1 | 262 | 219 | 83.588% | 87.581% | 219 | 0 | 241 | 91.985% | 94.698% | 0 | 1.445% |
| SFO | DJF | 11 | 0 | 222 | 175 | 78.829% | 83.689% | 175 | 0 | 175 | 78.829% | 83.689% | 0 | 1.701% |
| SFO | DJF | 11 | 1 | 228 | 170 | 74.561% | 79.775% | 170 | 0 | 198 | 86.842% | 90.625% | 0 | 1.657% |
| SFO | DJF | 12 | 0 | 242 | 158 | 65.289% | 71.006% | 158 | 0 | 158 | 65.289% | 71.006% | 0 | 1.563% |
| SFO | DJF | 12 | 1 | 208 | 123 | 59.135% | 65.591% | 123 | 0 | 160 | 76.923% | 82.129% | 0 | 1.813% |
| SFO | DJF | 13 | 0 | 258 | 110 | 42.636% | 48.735% | 110 | 0 | 110 | 42.636% | 48.735% | 0 | 1.467% |
| SFO | DJF | 13 | 1 | 192 | 70 | 36.458% | 43.470% | 70 | 0 | 106 | 55.208% | 62.072% | 0 | 1.962% |
| SFO | DJF | 14 | 0 | 275 | 71 | 25.818% | 31.299% | 71 | 0 | 71 | 25.818% | 31.299% | 0 | 1.378% |
| SFO | DJF | 14 | 1 | 175 | 31 | 17.714% | 24.046% | 31 | 0 | 55 | 31.429% | 38.643% | 0 | 2.148% |
| SFO | DJF | 15 | 0 | 275 | 22 | 8.000% | 11.815% | 22 | 0 | 22 | 8.000% | 11.815% | 0 | 1.378% |
| SFO | DJF | 15 | 1 | 175 | 15 | 8.571% | 13.660% | 15 | 0 | 20 | 11.429% | 16.993% | 0 | 2.148% |
| SFO | DJF | 16 | 0 | 277 | 12 | 4.332% | 7.418% | 12 | 0 | 12 | 4.332% | 7.418% | 0 | 1.368% |
| SFO | DJF | 16 | 1 | 173 | 6 | 3.468% | 7.359% | 6 | 0 | 9 | 5.202% | 9.590% | 0 | 2.172% |
| SFO | DJF | 17 | 0 | 275 | 6 | 2.182% | 4.677% | 6 | 0 | 6 | 2.182% | 4.677% | 0 | 1.378% |
| SFO | DJF | 17 | 1 | 175 | 5 | 2.857% | 6.513% | 5 | 0 | 7 | 4.000% | 8.025% | 0 | 2.148% |
| SFO | DJF | 18 | 0 | 275 | 5 | 1.818% | 4.185% | 5 | 0 | 5 | 1.818% | 4.185% | 0 | 1.378% |
| SFO | DJF | 18 | 1 | 175 | 5 | 2.857% | 6.513% | 5 | 0 | 6 | 3.429% | 7.277% | 0 | 2.148% |
| SFO | DJF | 19 | 0 | 276 | 5 | 1.812% | 4.170% | 5 | 0 | 5 | 1.812% | 4.170% | 0 | 1.373% |
| SFO | DJF | 19 | 1 | 174 | 3 | 1.724% | 4.946% | 3 | 0 | 4 | 2.299% | 5.761% | 0 | 2.160% |
| SFO | DJF | 20 | 0 | 277 | 4 | 1.444% | 3.653% | 4 | 0 | 4 | 1.444% | 3.653% | 0 | 1.368% |
| SFO | DJF | 20 | 1 | 173 | 3 | 1.734% | 4.974% | 3 | 0 | 3 | 1.734% | 4.974% | 0 | 2.172% |
| SFO | DJF | 21 | 0 | 278 | 5 | 1.799% | 4.140% | 5 | 0 | 5 | 1.799% | 4.140% | 0 | 1.363% |
| SFO | DJF | 21 | 1 | 172 | 1 | 0.581% | 3.219% | 1 | 0 | 1 | 0.581% | 3.219% | 0 | 2.185% |
| SFO | DJF | 22 | 0 | 277 | 3 | 1.083% | 3.135% | 3 | 0 | 3 | 1.083% | 3.135% | 0 | 1.368% |
| SFO | DJF | 22 | 1 | 173 | 0 | 0.000% | 2.172% | 0 | 0 | 1 | 0.578% | 3.201% | 0 | 2.172% |
| SFO | DJF | 23 | 0 | 276 | 0 | 0.000% | 1.373% | 0 | 0 | 0 | 0.000% | 1.373% | 0 | 1.373% |
| SFO | DJF | 23 | 1 | 174 | 0 | 0.000% | 2.160% | 0 | 0 | 0 | 0.000% | 2.160% | 0 | 2.160% |
| SFO | JJA | 00 | 0 | 336 | 336 | 100.000% | 100.000% | 336 | 0 | 336 | 100.000% | 100.000% | 0 | 1.130% |
| SFO | JJA | 00 | 1 | 122 | 122 | 100.000% | 100.000% | 122 | 0 | 122 | 100.000% | 100.000% | 0 | 3.053% |
| SFO | JJA | 01 | 0 | 332 | 332 | 100.000% | 100.000% | 332 | 0 | 332 | 100.000% | 100.000% | 0 | 1.144% |
| SFO | JJA | 01 | 1 | 126 | 126 | 100.000% | 100.000% | 126 | 0 | 126 | 100.000% | 100.000% | 0 | 2.959% |
| SFO | JJA | 02 | 0 | 333 | 333 | 100.000% | 100.000% | 333 | 0 | 333 | 100.000% | 100.000% | 0 | 1.140% |
| SFO | JJA | 02 | 1 | 125 | 125 | 100.000% | 100.000% | 125 | 0 | 125 | 100.000% | 100.000% | 0 | 2.982% |
| SFO | JJA | 03 | 0 | 335 | 335 | 100.000% | 100.000% | 335 | 0 | 335 | 100.000% | 100.000% | 0 | 1.134% |
| SFO | JJA | 03 | 1 | 123 | 123 | 100.000% | 100.000% | 123 | 0 | 123 | 100.000% | 100.000% | 0 | 3.029% |
| SFO | JJA | 04 | 0 | 337 | 337 | 100.000% | 100.000% | 337 | 0 | 337 | 100.000% | 100.000% | 0 | 1.127% |
| SFO | JJA | 04 | 1 | 121 | 121 | 100.000% | 100.000% | 121 | 0 | 121 | 100.000% | 100.000% | 0 | 3.077% |
| SFO | JJA | 05 | 0 | 308 | 308 | 100.000% | 100.000% | 308 | 0 | 308 | 100.000% | 100.000% | 0 | 1.232% |
| SFO | JJA | 05 | 1 | 150 | 150 | 100.000% | 100.000% | 150 | 0 | 150 | 100.000% | 100.000% | 0 | 2.497% |
| SFO | JJA | 06 | 0 | 335 | 335 | 100.000% | 100.000% | 335 | 0 | 335 | 100.000% | 100.000% | 0 | 1.134% |
| SFO | JJA | 06 | 1 | 123 | 123 | 100.000% | 100.000% | 123 | 0 | 123 | 100.000% | 100.000% | 0 | 3.029% |
| SFO | JJA | 07 | 0 | 336 | 336 | 100.000% | 100.000% | 336 | 0 | 336 | 100.000% | 100.000% | 0 | 1.130% |
| SFO | JJA | 07 | 1 | 122 | 120 | 98.361% | 99.549% | 120 | 0 | 121 | 99.180% | 99.855% | 0 | 3.053% |
| SFO | JJA | 08 | 0 | 268 | 267 | 99.627% | 99.934% | 267 | 0 | 267 | 99.627% | 99.934% | 0 | 1.413% |
| SFO | JJA | 08 | 1 | 190 | 187 | 98.421% | 99.462% | 187 | 0 | 189 | 99.474% | 99.907% | 0 | 1.982% |
| SFO | JJA | 09 | 0 | 207 | 202 | 97.585% | 98.964% | 202 | 0 | 202 | 97.585% | 98.964% | 0 | 1.822% |
| SFO | JJA | 09 | 1 | 251 | 241 | 96.016% | 97.822% | 241 | 0 | 245 | 97.610% | 98.900% | 0 | 1.507% |
| SFO | JJA | 10 | 0 | 166 | 154 | 92.771% | 95.817% | 154 | 0 | 154 | 92.771% | 95.817% | 0 | 2.262% |
| SFO | JJA | 10 | 1 | 292 | 240 | 82.192% | 86.153% | 240 | 0 | 259 | 88.699% | 91.839% | 0 | 1.298% |
| SFO | JJA | 11 | 0 | 149 | 99 | 66.443% | 73.527% | 99 | 0 | 99 | 66.443% | 73.527% | 0 | 2.513% |
| SFO | JJA | 11 | 1 | 309 | 177 | 57.282% | 62.674% | 177 | 0 | 209 | 67.638% | 72.610% | 0 | 1.228% |
| SFO | JJA | 12 | 0 | 161 | 60 | 37.267% | 44.951% | 60 | 0 | 60 | 37.267% | 44.951% | 0 | 2.330% |
| SFO | JJA | 12 | 1 | 297 | 85 | 28.620% | 34.007% | 85 | 0 | 111 | 37.374% | 43.004% | 0 | 1.277% |
| SFO | JJA | 13 | 0 | 169 | 23 | 13.609% | 19.594% | 23 | 0 | 23 | 13.609% | 19.594% | 0 | 2.223% |
| SFO | JJA | 13 | 1 | 289 | 22 | 7.612% | 11.256% | 22 | 0 | 35 | 12.111% | 16.377% | 0 | 1.312% |
| SFO | JJA | 14 | 0 | 172 | 8 | 4.651% | 8.908% | 8 | 0 | 8 | 4.651% | 8.908% | 0 | 2.185% |
| SFO | JJA | 14 | 1 | 286 | 2 | 0.699% | 2.513% | 2 | 0 | 7 | 2.448% | 4.965% | 0 | 1.325% |
| SFO | JJA | 15 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 15 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 16 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 16 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 17 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 17 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 18 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 18 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 19 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 19 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 20 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 20 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 21 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 21 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 22 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 22 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | JJA | 23 | 0 | 171 | 0 | 0.000% | 2.197% | 0 | 0 | 0 | 0.000% | 2.197% | 0 | 2.197% |
| SFO | JJA | 23 | 1 | 287 | 0 | 0.000% | 1.321% | 0 | 0 | 0 | 0.000% | 1.321% | 0 | 1.321% |
| SFO | MAM | 00 | 0 | 118 | 117 | 99.153% | 99.850% | 117 | 0 | 117 | 99.153% | 99.850% | 0 | 3.153% |
| SFO | MAM | 00 | 1 | 340 | 337 | 99.118% | 99.699% | 337 | 0 | 339 | 99.706% | 99.948% | 0 | 1.117% |
| SFO | MAM | 01 | 0 | 116 | 115 | 99.138% | 99.848% | 115 | 0 | 115 | 99.138% | 99.848% | 0 | 3.205% |
| SFO | MAM | 01 | 1 | 342 | 338 | 98.830% | 99.544% | 338 | 0 | 341 | 99.708% | 99.948% | 0 | 1.111% |
| SFO | MAM | 02 | 0 | 117 | 116 | 99.145% | 99.849% | 116 | 0 | 116 | 99.145% | 99.849% | 0 | 3.179% |
| SFO | MAM | 02 | 1 | 341 | 337 | 98.827% | 99.543% | 337 | 0 | 340 | 99.707% | 99.948% | 0 | 1.114% |
| SFO | MAM | 03 | 0 | 120 | 119 | 99.167% | 99.853% | 119 | 0 | 119 | 99.167% | 99.853% | 0 | 3.102% |
| SFO | MAM | 03 | 1 | 338 | 334 | 98.817% | 99.539% | 334 | 0 | 337 | 99.704% | 99.948% | 0 | 1.124% |
| SFO | MAM | 04 | 0 | 120 | 119 | 99.167% | 99.853% | 119 | 0 | 119 | 99.167% | 99.853% | 0 | 3.102% |
| SFO | MAM | 04 | 1 | 338 | 333 | 98.521% | 99.367% | 333 | 0 | 337 | 99.704% | 99.948% | 0 | 1.124% |
| SFO | MAM | 05 | 0 | 118 | 117 | 99.153% | 99.850% | 117 | 0 | 117 | 99.153% | 99.850% | 0 | 3.153% |
| SFO | MAM | 05 | 1 | 340 | 335 | 98.529% | 99.370% | 335 | 0 | 339 | 99.706% | 99.948% | 0 | 1.117% |
| SFO | MAM | 06 | 0 | 152 | 150 | 98.684% | 99.638% | 150 | 0 | 150 | 98.684% | 99.638% | 0 | 2.465% |
| SFO | MAM | 06 | 1 | 306 | 302 | 98.693% | 99.491% | 302 | 0 | 305 | 99.673% | 99.942% | 0 | 1.240% |
| SFO | MAM | 07 | 0 | 194 | 191 | 98.454% | 99.473% | 191 | 0 | 191 | 98.454% | 99.473% | 0 | 1.942% |
| SFO | MAM | 07 | 1 | 264 | 261 | 98.864% | 99.613% | 261 | 0 | 263 | 99.621% | 99.933% | 0 | 1.434% |
| SFO | MAM | 08 | 0 | 261 | 258 | 98.851% | 99.608% | 258 | 0 | 258 | 98.851% | 99.608% | 0 | 1.450% |
| SFO | MAM | 08 | 1 | 197 | 194 | 98.477% | 99.481% | 194 | 0 | 196 | 99.492% | 99.910% | 0 | 1.913% |
| SFO | MAM | 09 | 0 | 272 | 262 | 96.324% | 97.991% | 262 | 0 | 262 | 96.324% | 97.991% | 0 | 1.393% |
| SFO | MAM | 09 | 1 | 186 | 173 | 93.011% | 95.870% | 173 | 0 | 180 | 96.774% | 98.513% | 0 | 2.024% |
| SFO | MAM | 10 | 0 | 275 | 242 | 88.000% | 91.326% | 242 | 0 | 242 | 88.000% | 91.326% | 0 | 1.378% |
| SFO | MAM | 10 | 1 | 183 | 140 | 76.503% | 82.062% | 140 | 0 | 158 | 86.339% | 90.572% | 0 | 2.056% |
| SFO | MAM | 11 | 0 | 266 | 182 | 68.421% | 73.711% | 182 | 0 | 182 | 68.421% | 73.711% | 0 | 1.424% |
| SFO | MAM | 11 | 1 | 192 | 97 | 50.521% | 57.513% | 97 | 0 | 123 | 64.062% | 70.512% | 0 | 1.962% |
| SFO | MAM | 12 | 0 | 257 | 96 | 37.354% | 43.414% | 96 | 0 | 96 | 37.354% | 43.414% | 0 | 1.473% |
| SFO | MAM | 12 | 1 | 201 | 49 | 24.378% | 30.758% | 49 | 0 | 73 | 36.318% | 43.166% | 0 | 1.875% |
| SFO | MAM | 13 | 0 | 260 | 57 | 21.923% | 27.341% | 57 | 0 | 57 | 21.923% | 27.341% | 0 | 1.456% |
| SFO | MAM | 13 | 1 | 198 | 12 | 6.061% | 10.293% | 12 | 0 | 21 | 10.606% | 15.669% | 0 | 1.903% |
| SFO | MAM | 14 | 0 | 247 | 16 | 6.478% | 10.262% | 16 | 0 | 16 | 6.478% | 10.262% | 0 | 1.531% |
| SFO | MAM | 14 | 1 | 211 | 3 | 1.422% | 4.096% | 3 | 0 | 5 | 2.370% | 5.426% | 0 | 1.788% |
| SFO | MAM | 15 | 0 | 243 | 4 | 1.646% | 4.155% | 4 | 0 | 4 | 1.646% | 4.155% | 0 | 1.556% |
| SFO | MAM | 15 | 1 | 215 | 1 | 0.465% | 2.587% | 1 | 0 | 1 | 0.465% | 2.587% | 0 | 1.755% |
| SFO | MAM | 16 | 0 | 242 | 0 | 0.000% | 1.563% | 0 | 0 | 0 | 0.000% | 1.563% | 0 | 1.563% |
| SFO | MAM | 16 | 1 | 216 | 1 | 0.463% | 2.575% | 1 | 0 | 1 | 0.463% | 2.575% | 0 | 1.747% |
| SFO | MAM | 17 | 0 | 243 | 1 | 0.412% | 2.294% | 1 | 0 | 1 | 0.412% | 2.294% | 0 | 1.556% |
| SFO | MAM | 17 | 1 | 215 | 0 | 0.000% | 1.755% | 0 | 0 | 0 | 0.000% | 1.755% | 0 | 1.755% |
| SFO | MAM | 18 | 0 | 242 | 0 | 0.000% | 1.563% | 0 | 0 | 0 | 0.000% | 1.563% | 0 | 1.563% |
| SFO | MAM | 18 | 1 | 216 | 1 | 0.463% | 2.575% | 1 | 0 | 1 | 0.463% | 2.575% | 0 | 1.747% |
| SFO | MAM | 19 | 0 | 242 | 0 | 0.000% | 1.563% | 0 | 0 | 0 | 0.000% | 1.563% | 0 | 1.563% |
| SFO | MAM | 19 | 1 | 216 | 1 | 0.463% | 2.575% | 1 | 0 | 1 | 0.463% | 2.575% | 0 | 1.747% |
| SFO | MAM | 20 | 0 | 243 | 1 | 0.412% | 2.294% | 1 | 0 | 1 | 0.412% | 2.294% | 0 | 1.556% |
| SFO | MAM | 20 | 1 | 215 | 0 | 0.000% | 1.755% | 0 | 0 | 0 | 0.000% | 1.755% | 0 | 1.755% |
| SFO | MAM | 21 | 0 | 243 | 1 | 0.412% | 2.294% | 1 | 0 | 1 | 0.412% | 2.294% | 0 | 1.556% |
| SFO | MAM | 21 | 1 | 215 | 0 | 0.000% | 1.755% | 0 | 0 | 0 | 0.000% | 1.755% | 0 | 1.755% |
| SFO | MAM | 22 | 0 | 243 | 1 | 0.412% | 2.294% | 1 | 0 | 1 | 0.412% | 2.294% | 0 | 1.556% |
| SFO | MAM | 22 | 1 | 215 | 0 | 0.000% | 1.755% | 0 | 0 | 0 | 0.000% | 1.755% | 0 | 1.755% |
| SFO | MAM | 23 | 0 | 242 | 0 | 0.000% | 1.563% | 0 | 0 | 0 | 0.000% | 1.563% | 0 | 1.563% |
| SFO | MAM | 23 | 1 | 216 | 0 | 0.000% | 1.747% | 0 | 0 | 0 | 0.000% | 1.747% | 0 | 1.747% |
| SFO | SON | 00 | 0 | 272 | 268 | 98.529% | 99.427% | 268 | 0 | 268 | 98.529% | 99.427% | 0 | 1.393% |
| SFO | SON | 00 | 1 | 182 | 177 | 97.253% | 98.821% | 177 | 0 | 181 | 99.451% | 99.903% | 0 | 2.067% |
| SFO | SON | 01 | 0 | 274 | 270 | 98.540% | 99.431% | 270 | 0 | 270 | 98.540% | 99.431% | 0 | 1.383% |
| SFO | SON | 01 | 1 | 180 | 175 | 97.222% | 98.808% | 175 | 0 | 179 | 99.444% | 99.902% | 0 | 2.090% |
| SFO | SON | 02 | 0 | 272 | 268 | 98.529% | 99.427% | 268 | 0 | 268 | 98.529% | 99.427% | 0 | 1.393% |
| SFO | SON | 02 | 1 | 182 | 177 | 97.253% | 98.821% | 177 | 0 | 181 | 99.451% | 99.903% | 0 | 2.067% |
| SFO | SON | 03 | 0 | 276 | 272 | 98.551% | 99.435% | 272 | 0 | 272 | 98.551% | 99.435% | 0 | 1.373% |
| SFO | SON | 03 | 1 | 178 | 173 | 97.191% | 98.794% | 173 | 0 | 177 | 99.438% | 99.901% | 0 | 2.113% |
| SFO | SON | 04 | 0 | 271 | 267 | 98.524% | 99.425% | 267 | 0 | 267 | 98.524% | 99.425% | 0 | 1.398% |
| SFO | SON | 04 | 1 | 183 | 178 | 97.268% | 98.827% | 178 | 0 | 182 | 99.454% | 99.903% | 0 | 2.056% |
| SFO | SON | 05 | 0 | 273 | 269 | 98.535% | 99.429% | 269 | 0 | 269 | 98.535% | 99.429% | 0 | 1.388% |
| SFO | SON | 05 | 1 | 181 | 176 | 97.238% | 98.814% | 176 | 0 | 180 | 99.448% | 99.902% | 0 | 2.078% |
| SFO | SON | 06 | 0 | 276 | 271 | 98.188% | 99.224% | 271 | 0 | 271 | 98.188% | 99.224% | 0 | 1.373% |
| SFO | SON | 06 | 1 | 178 | 173 | 97.191% | 98.794% | 173 | 0 | 177 | 99.438% | 99.901% | 0 | 2.113% |
| SFO | SON | 07 | 0 | 278 | 273 | 98.201% | 99.229% | 273 | 0 | 273 | 98.201% | 99.229% | 0 | 1.363% |
| SFO | SON | 07 | 1 | 176 | 171 | 97.159% | 98.781% | 171 | 0 | 175 | 99.432% | 99.900% | 0 | 2.136% |
| SFO | SON | 08 | 0 | 261 | 254 | 97.318% | 98.695% | 254 | 0 | 254 | 97.318% | 98.695% | 0 | 1.450% |
| SFO | SON | 08 | 1 | 193 | 189 | 97.927% | 99.191% | 189 | 0 | 192 | 99.482% | 99.908% | 0 | 1.952% |
| SFO | SON | 09 | 0 | 239 | 231 | 96.653% | 98.294% | 231 | 0 | 231 | 96.653% | 98.294% | 0 | 1.582% |
| SFO | SON | 09 | 1 | 215 | 202 | 93.953% | 96.433% | 202 | 0 | 208 | 96.744% | 98.414% | 0 | 1.755% |
| SFO | SON | 10 | 0 | 218 | 199 | 91.284% | 94.349% | 199 | 0 | 199 | 91.284% | 94.349% | 0 | 1.732% |
| SFO | SON | 10 | 1 | 236 | 209 | 88.559% | 92.017% | 209 | 0 | 219 | 92.797% | 95.454% | 0 | 1.602% |
| SFO | SON | 11 | 0 | 207 | 162 | 78.261% | 83.337% | 162 | 0 | 162 | 78.261% | 83.337% | 0 | 1.822% |
| SFO | SON | 11 | 1 | 247 | 162 | 65.587% | 71.232% | 162 | 0 | 191 | 77.328% | 82.108% | 0 | 1.531% |
| SFO | SON | 12 | 0 | 209 | 120 | 57.416% | 63.927% | 120 | 0 | 120 | 57.416% | 63.927% | 0 | 1.805% |
| SFO | SON | 12 | 1 | 245 | 103 | 42.041% | 48.298% | 103 | 0 | 128 | 52.245% | 58.416% | 0 | 1.544% |
| SFO | SON | 13 | 0 | 218 | 70 | 32.110% | 38.572% | 70 | 0 | 70 | 32.110% | 38.572% | 0 | 1.732% |
| SFO | SON | 13 | 1 | 236 | 45 | 19.068% | 24.559% | 45 | 0 | 60 | 25.424% | 31.342% | 0 | 1.602% |
| SFO | SON | 14 | 0 | 215 | 33 | 15.349% | 20.771% | 33 | 0 | 33 | 15.349% | 20.771% | 0 | 1.755% |
| SFO | SON | 14 | 1 | 239 | 12 | 5.021% | 8.570% | 12 | 0 | 13 | 5.439% | 9.082% | 0 | 1.582% |
| SFO | SON | 15 | 0 | 200 | 5 | 2.500% | 5.718% | 5 | 0 | 5 | 2.500% | 5.718% | 0 | 1.885% |
| SFO | SON | 15 | 1 | 254 | 4 | 1.575% | 3.978% | 4 | 0 | 5 | 1.969% | 4.525% | 0 | 1.490% |
| SFO | SON | 16 | 0 | 200 | 1 | 0.500% | 2.777% | 1 | 0 | 1 | 0.500% | 2.777% | 0 | 1.885% |
| SFO | SON | 16 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 17 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 17 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 18 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 18 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 19 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 19 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 20 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 20 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 21 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 21 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 22 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 22 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |
| SFO | SON | 23 | 0 | 200 | 0 | 0.000% | 1.885% | 0 | 0 | 0 | 0.000% | 1.885% | 0 | 1.885% |
| SFO | SON | 23 | 1 | 254 | 0 | 0.000% | 1.490% | 0 | 0 | 0 | 0.000% | 1.490% | 0 | 1.490% |

## 8. Limitations

* `R(t)` is ASOS-derived and settlement is the CLI integer. §2 measures that
  basis; it is a real, irreducible source of error in any rule driven by
  `R(t)`. No hourly CLI-basis `R(t)` is measurable from this archive.
* NYC is hourly-cadence; the other four are 5-minute. An hourly station's
  `R(t)` is a coarser lower bound on the true running maximum, which biases
  its exceedance and crossing rates UPWARD relative to a 5-minute station.
  The tables are per-station and never pooled, so this does not contaminate
  the others.
* Rung phase is assumed even (`[A, A+1]`, A even). An odd-phase ladder simply
  swaps the two headroom labels; both are reported, so both phases are
  covered.
* The completeness filter is strict (all 24 hours). §1 reports what it drops.
* **Resolution floor.** A zero-event cell of size `n` reports a Wilson
  upper of `z²/(n + z²)`. With ~200–300 station-days per per-season cell
  that floor is ~1.4–2.2%, and ~0.4% season-pooled. Reference levels below
  those are unreachable HERE regardless of the physics; §5.0 tabulates it
  and §0.1 refuses to issue a verdict below it.
* **`T*` is estimated two ways and they differ by ~1h at every station, in
  BOTH DST and standard months** (§3.3). That rules out the `(LST)` label
  being a disguised daylight-time field, but it leaves the two estimates
  genuinely disagreeing; neither is adjusted to match the other.
* Preliminaries are scanned for implausibility (§4, PR-3) but the crossing
  tables use FINALS only, because the final is what settles. A rule reading
  a preliminary running max carries the PR-3 hazard rate on top of
  everything in §5.
* This study measures physics. It says nothing about whether any of it is
  tradable: no price, spread, depth, fee or fill appears in it. That question
  belongs to NautilusTrader, and to order-book data Breezy does not yet hold.
