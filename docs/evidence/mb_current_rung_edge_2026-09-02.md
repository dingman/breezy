# M_B -- current-rung p_hold x ask edge measurement and its kill

Generated 2026-09-02T23:35:26+00:00 from
`scripts/analysis/mb_current_rung_edge_study.py`. Spec:
`docs/evidence/grok_mb_design_2026-09-02.md` SS1 / SS2.

A descriptive join, not a backtest: no order, fill, position, fee or P&L appears anywhere in this pipeline. NautilusTrader is the exclusive owner of backtesting and execution.

> **Audit 2026-09-02 23:10Z (prediction-market-reviewer, independent recomputation):** Part A is
> CORRECT — MDW-SON-h12 m=0 reproduced exactly (n=455, 291 holds, Wilson-lower 0.5944); LST
> alignment uses fixed standard offsets (`climate_day.py:24-35`); R(h) is through h:59; m=0/m=1
> are separate cells selected by the real ladder in Part B; the ASOS→CLI basis biases p_hold DOWN
> (CLI > ASOS day-end max on 284/1825 MDW days, all scored as misses). **Interpretation
> corrected:** the archive p_hold is an unconditional climatological base rate; the venue ask is
> information-conditioned (forecast, trend). On 09-01 MDW the day settled 93 > the noon rung
> [91,92] — the market's 0.06 was right. A base-rate edge is not evidence of mispricing; the
> discriminating statistic is the REALIZED hold rate of taken current-rung trials vs ask + fee
> (Wilson upper bound), which needs n ≈ 60–150 trials. **Kill amendment implemented**
> (`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`): see the per-lag "Realized-hold evidence"
> tables and the Family verdict section below.

## Tape integrity (LESSON L-8) -- verified before interpretation

> breezy-quote-tape-preflight over /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us: all 989 staged files carrying M_A's target station-day instruments are INTACT -- 1252168 rows, 0 truncated, 0 unreadable, 0 empty.

## Part A -- archive p_hold table (JJA / SON, h=13 and h=15)

| station | season | h | width | m | n | holds | rate | Wilson-lower |
|---|---|---:|---|---|---:|---:|---:|---:|
| SFO | JJA | 13 | interior_2F | 0 | 446 | 329 | 0.7377 | 0.6949 |
| SFO | JJA | 13 | interior_2F | 1 | 446 | 291 | 0.6525 | 0.6071 |
| SFO | JJA | 13 | open_upper | - | 446 | 363 | 0.8139 | 0.7752 |
| SFO | JJA | 15 | interior_2F | 0 | 446 | 343 | 0.7691 | 0.7277 |
| SFO | JJA | 15 | interior_2F | 1 | 446 | 342 | 0.7668 | 0.7254 |
| SFO | JJA | 15 | open_upper | - | 446 | 351 | 0.7870 | 0.7466 |
| SFO | SON | 13 | interior_2F | 0 | 450 | 315 | 0.7000 | 0.6561 |
| SFO | SON | 13 | interior_2F | 1 | 450 | 240 | 0.5333 | 0.4872 |
| SFO | SON | 13 | open_upper | - | 450 | 408 | 0.9067 | 0.8762 |
| SFO | SON | 15 | interior_2F | 0 | 450 | 383 | 0.8511 | 0.8153 |
| SFO | SON | 15 | interior_2F | 1 | 450 | 336 | 0.7467 | 0.7045 |
| SFO | SON | 15 | open_upper | - | 450 | 391 | 0.8689 | 0.8346 |
| MIA | JJA | 13 | interior_2F | 0 | 450 | 389 | 0.8644 | 0.8297 |
| MIA | JJA | 13 | interior_2F | 1 | 450 | 298 | 0.6622 | 0.6173 |
| MIA | JJA | 13 | open_upper | - | 450 | 407 | 0.9044 | 0.8738 |
| MIA | JJA | 15 | interior_2F | 0 | 450 | 395 | 0.8778 | 0.8443 |
| MIA | JJA | 15 | interior_2F | 1 | 450 | 335 | 0.7444 | 0.7022 |
| MIA | JJA | 15 | open_upper | - | 450 | 399 | 0.8867 | 0.8540 |
| MIA | SON | 13 | interior_2F | 0 | 448 | 364 | 0.8125 | 0.7738 |
| MIA | SON | 13 | interior_2F | 1 | 448 | 296 | 0.6607 | 0.6157 |
| MIA | SON | 13 | open_upper | - | 448 | 379 | 0.8460 | 0.8096 |
| MIA | SON | 15 | interior_2F | 0 | 448 | 368 | 0.8214 | 0.7833 |
| MIA | SON | 15 | interior_2F | 1 | 448 | 332 | 0.7411 | 0.6986 |
| MIA | SON | 15 | open_upper | - | 448 | 369 | 0.8237 | 0.7857 |
| MDW | JJA | 13 | interior_2F | 0 | 459 | 351 | 0.7647 | 0.7238 |
| MDW | JJA | 13 | interior_2F | 1 | 459 | 249 | 0.5425 | 0.4967 |
| MDW | JJA | 13 | open_upper | - | 459 | 410 | 0.8932 | 0.8617 |
| MDW | JJA | 15 | interior_2F | 0 | 459 | 377 | 0.8214 | 0.7837 |
| MDW | JJA | 15 | interior_2F | 1 | 459 | 356 | 0.7756 | 0.7352 |
| MDW | JJA | 15 | open_upper | - | 459 | 384 | 0.8366 | 0.8000 |
| MDW | SON | 13 | interior_2F | 0 | 455 | 358 | 0.7868 | 0.7469 |
| MDW | SON | 13 | interior_2F | 1 | 455 | 278 | 0.6110 | 0.5654 |
| MDW | SON | 13 | open_upper | - | 455 | 394 | 0.8659 | 0.8315 |
| MDW | SON | 15 | interior_2F | 0 | 455 | 361 | 0.7934 | 0.7538 |
| MDW | SON | 15 | interior_2F | 1 | 455 | 366 | 0.8044 | 0.7655 |
| MDW | SON | 15 | open_upper | - | 455 | 372 | 0.8176 | 0.7795 |
| LAX | JJA | 13 | interior_2F | 0 | 455 | 371 | 0.8154 | 0.7771 |
| LAX | JJA | 13 | interior_2F | 1 | 455 | 314 | 0.6901 | 0.6462 |
| LAX | JJA | 13 | open_upper | - | 455 | 386 | 0.8484 | 0.8125 |
| LAX | JJA | 15 | interior_2F | 0 | 455 | 371 | 0.8154 | 0.7771 |
| LAX | JJA | 15 | interior_2F | 1 | 455 | 332 | 0.7297 | 0.6871 |
| LAX | JJA | 15 | open_upper | - | 455 | 380 | 0.8352 | 0.7983 |
| LAX | SON | 13 | interior_2F | 0 | 451 | 341 | 0.7561 | 0.7144 |
| LAX | SON | 13 | interior_2F | 1 | 451 | 309 | 0.6851 | 0.6409 |
| LAX | SON | 13 | open_upper | - | 451 | 366 | 0.8115 | 0.7729 |
| LAX | SON | 15 | interior_2F | 0 | 451 | 342 | 0.7583 | 0.7167 |
| LAX | SON | 15 | interior_2F | 1 | 451 | 320 | 0.7095 | 0.6660 |
| LAX | SON | 15 | open_upper | - | 451 | 361 | 0.8004 | 0.7611 |

### Pre-filter: interior m=1 is dead at every station/hour (all seasons)

| station | season | h | n | holds | rate | Wilson-lower |
|---|---|---:|---:|---:|---:|---:|
| LAX | DJF | 12 | 447 | 253 | 0.5660 | 0.5197 |
| LAX | DJF | 13 | 447 | 304 | 0.6801 | 0.6355 |
| LAX | DJF | 14 | 447 | 330 | 0.7383 | 0.6956 |
| LAX | DJF | 15 | 447 | 337 | 0.7539 | 0.7119 |
| LAX | DJF | 16 | 447 | 340 | 0.7606 | 0.7190 |
| LAX | JJA | 12 | 455 | 276 | 0.6066 | 0.5610 |
| LAX | JJA | 13 | 455 | 314 | 0.6901 | 0.6462 |
| LAX | JJA | 14 | 455 | 330 | 0.7253 | 0.6825 |
| LAX | JJA | 15 | 455 | 332 | 0.7297 | 0.6871 |
| LAX | JJA | 16 | 455 | 334 | 0.7341 | 0.6916 |
| LAX | MAM | 12 | 459 | 297 | 0.6471 | 0.6023 |
| LAX | MAM | 13 | 459 | 338 | 0.7364 | 0.6942 |
| LAX | MAM | 14 | 459 | 345 | 0.7516 | 0.7101 |
| LAX | MAM | 15 | 459 | 347 | 0.7560 | 0.7147 |
| LAX | MAM | 16 | 459 | 347 | 0.7560 | 0.7147 |
| LAX | SON | 12 | 451 | 282 | 0.6253 | 0.5797 |
| LAX | SON | 13 | 451 | 309 | 0.6851 | 0.6409 |
| LAX | SON | 14 | 451 | 319 | 0.7073 | 0.6637 |
| LAX | SON | 15 | 451 | 320 | 0.7095 | 0.6660 |
| LAX | SON | 16 | 451 | 322 | 0.7140 | 0.6706 |
| MDW | DJF | 12 | 451 | 185 | 0.4102 | 0.3657 |
| MDW | DJF | 13 | 451 | 267 | 0.5920 | 0.5461 |
| MDW | DJF | 14 | 451 | 319 | 0.7073 | 0.6637 |
| MDW | DJF | 15 | 451 | 347 | 0.7694 | 0.7283 |
| MDW | DJF | 16 | 451 | 356 | 0.7894 | 0.7494 |
| MDW | JJA | 12 | 459 | 157 | 0.3420 | 0.3001 |
| MDW | JJA | 13 | 459 | 249 | 0.5425 | 0.4967 |
| MDW | JJA | 14 | 459 | 327 | 0.7124 | 0.6694 |
| MDW | JJA | 15 | 459 | 356 | 0.7756 | 0.7352 |
| MDW | JJA | 16 | 459 | 366 | 0.7974 | 0.7582 |
| MDW | MAM | 12 | 460 | 172 | 0.3739 | 0.3309 |
| MDW | MAM | 13 | 460 | 240 | 0.5217 | 0.4761 |
| MDW | MAM | 14 | 460 | 307 | 0.6674 | 0.6231 |
| MDW | MAM | 15 | 460 | 353 | 0.7674 | 0.7267 |
| MDW | MAM | 16 | 460 | 368 | 0.8000 | 0.7610 |
| MDW | SON | 12 | 455 | 183 | 0.4022 | 0.3581 |
| MDW | SON | 13 | 455 | 278 | 0.6110 | 0.5654 |
| MDW | SON | 14 | 455 | 343 | 0.7538 | 0.7122 |
| MDW | SON | 15 | 455 | 366 | 0.8044 | 0.7655 |
| MDW | SON | 16 | 455 | 369 | 0.8110 | 0.7725 |
| MIA | DJF | 12 | 450 | 202 | 0.4489 | 0.4036 |
| MIA | DJF | 13 | 450 | 279 | 0.6200 | 0.5743 |
| MIA | DJF | 14 | 450 | 324 | 0.7200 | 0.6768 |
| MIA | DJF | 15 | 450 | 342 | 0.7600 | 0.7184 |
| MIA | DJF | 16 | 450 | 344 | 0.7644 | 0.7231 |
| MIA | JJA | 12 | 450 | 241 | 0.5356 | 0.4894 |
| MIA | JJA | 13 | 450 | 298 | 0.6622 | 0.6173 |
| MIA | JJA | 14 | 450 | 323 | 0.7178 | 0.6745 |
| MIA | JJA | 15 | 450 | 335 | 0.7444 | 0.7022 |
| MIA | JJA | 16 | 450 | 335 | 0.7444 | 0.7022 |
| MIA | MAM | 12 | 450 | 202 | 0.4489 | 0.4036 |
| MIA | MAM | 13 | 450 | 274 | 0.6089 | 0.5631 |
| MIA | MAM | 14 | 450 | 307 | 0.6822 | 0.6378 |
| MIA | MAM | 15 | 450 | 320 | 0.7111 | 0.6676 |
| MIA | MAM | 16 | 450 | 324 | 0.7200 | 0.6768 |
| MIA | SON | 12 | 448 | 252 | 0.5625 | 0.5162 |
| MIA | SON | 13 | 448 | 296 | 0.6607 | 0.6157 |
| MIA | SON | 14 | 448 | 326 | 0.7277 | 0.6847 |
| MIA | SON | 15 | 448 | 332 | 0.7411 | 0.6986 |
| MIA | SON | 16 | 448 | 333 | 0.7433 | 0.7009 |
| SFO | DJF | 12 | 445 | 108 | 0.2427 | 0.2052 |
| SFO | DJF | 13 | 445 | 188 | 0.4225 | 0.3774 |
| SFO | DJF | 14 | 445 | 258 | 0.5798 | 0.5334 |
| SFO | DJF | 15 | 445 | 324 | 0.7281 | 0.6849 |
| SFO | DJF | 16 | 445 | 342 | 0.7685 | 0.7272 |
| SFO | JJA | 12 | 446 | 204 | 0.4574 | 0.4117 |
| SFO | JJA | 13 | 446 | 291 | 0.6525 | 0.6071 |
| SFO | JJA | 14 | 446 | 331 | 0.7422 | 0.6996 |
| SFO | JJA | 15 | 446 | 342 | 0.7668 | 0.7254 |
| SFO | JJA | 16 | 446 | 342 | 0.7668 | 0.7254 |
| SFO | MAM | 12 | 452 | 211 | 0.4668 | 0.4213 |
| SFO | MAM | 13 | 452 | 283 | 0.6261 | 0.5806 |
| SFO | MAM | 14 | 452 | 329 | 0.7279 | 0.6851 |
| SFO | MAM | 15 | 452 | 344 | 0.7611 | 0.7197 |
| SFO | MAM | 16 | 452 | 348 | 0.7699 | 0.7289 |
| SFO | SON | 12 | 450 | 150 | 0.3333 | 0.2914 |
| SFO | SON | 13 | 450 | 240 | 0.5333 | 0.4872 |
| SFO | SON | 14 | 450 | 306 | 0.6800 | 0.6355 |
| SFO | SON | 15 | 450 | 336 | 0.7467 | 0.7045 |
| SFO | SON | 16 | 450 | 343 | 0.7622 | 0.7208 |

## Part B -- tape join, per-station-day, per lag

### lag = 5 min

| station | day | status | coverage (min) | h | m | width | held | ask | size | p_hold_lower | edge | taken |
|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---|
| LAX | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| LAX | 2026-09-01 | SCORED | 299.9 | 12 | - | open_lower | False | 0.1700 | 28.0000 | n/a | n/a |  |
| MDW | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MDW | 2026-09-01 | SCORED | 300.0 | 12 | 0 | interior_2F | False | 0.0600 | 41.0000 | 0.5944 | +0.5311 | TAKEN |
| MIA | 2026-08-30 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-09-01 | SCORED | 299.9 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-09-01 | SCORED | 299.9 | 12 | 0 | interior_2F | True | 0.6600 | 24.0100 | 0.4606 | -0.2129 |  |

#### Realized-hold evidence (kill amendment: `docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)

| stratum | n | k | realized rate | mean ask | break-even | Wilson-lower | Wilson-upper | |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| pooled | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| station:MDW | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| ask_band:0.05-0.15 | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |

**UNDERPOWERED** (lag=5min) -- lag=5min: n_taken=1; kill needs n>=60, survive needs n>=150 -- not dead, not alive

### lag = 10 min

| station | day | status | coverage (min) | h | m | width | held | ask | size | p_hold_lower | edge | taken |
|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---|
| LAX | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| LAX | 2026-09-01 | SCORED | 299.9 | 12 | - | open_lower | False | 0.1700 | 175.0000 | n/a | n/a |  |
| MDW | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MDW | 2026-09-01 | SCORED | 300.0 | 12 | 0 | interior_2F | False | 0.0600 | 40.0000 | 0.5944 | +0.5311 | TAKEN |
| MIA | 2026-08-30 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-09-01 | SCORED | 299.9 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-09-01 | SCORED | 299.9 | 12 | 0 | interior_2F | True | 0.6600 | 29.0100 | 0.4606 | -0.2129 |  |

#### Realized-hold evidence (kill amendment: `docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)

| stratum | n | k | realized rate | mean ask | break-even | Wilson-lower | Wilson-upper | |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| pooled | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| station:MDW | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| ask_band:0.05-0.15 | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |

**UNDERPOWERED** (lag=10min) -- lag=10min: n_taken=1; kill needs n>=60, survive needs n>=150 -- not dead, not alive

### lag = 15 min

| station | day | status | coverage (min) | h | m | width | held | ask | size | p_hold_lower | edge | taken |
|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---|
| LAX | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| LAX | 2026-09-01 | SCORED | 299.9 | 12 | - | open_lower | False | 0.0800 | 150.0000 | n/a | n/a |  |
| MDW | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MDW | 2026-09-01 | SCORED | 300.0 | 12 | 0 | interior_2F | False | 0.0600 | 65.0000 | 0.5944 | +0.5311 | TAKEN |
| MIA | 2026-08-30 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-08-31 | SCORED | 0.0 | - | - | - | - | - | - | - | - | - |
| MIA | 2026-09-01 | SCORED | 299.9 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-08-31 | SCORED | 19.0 | - | - | - | - | - | - | - | - | - |
| SFO | 2026-09-01 | SCORED | 299.9 | 12 | 0 | interior_2F | True | 0.6600 | 29.0100 | 0.4606 | -0.2129 |  |

#### Realized-hold evidence (kill amendment: `docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)

| stratum | n | k | realized rate | mean ask | break-even | Wilson-lower | Wilson-upper | |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| pooled | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| station:MDW | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |
| ask_band:0.05-0.15 | 1 | 0 | 0.0000 | 0.0600 | 0.0634 | 0.0000 | 0.7935 |  |

**UNDERPOWERED** (lag=15min) -- lag=15min: n_taken=1; kill needs n>=60, survive needs n>=150 -- not dead, not alive

## Family verdict (both K-B lags, 10 and 15, must agree)

**UNDERPOWERED**

## Independence and the clock

One trial per station-day; snapshot-weighted pools are forbidden. Same-calendar-day stations are weakly dependent (shared synoptic weather) -- the Wilson interval is anti-conservative when treating several same-day station-days as independent draws (`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`).

Clock (memo): ~3 taken trials/day at the archive's dense-station rate -> n=60 around 2026-09-22, n=150 around 2026-10-21, both still SON. If taken stays at the 09-01 rate (~1/day), n=60/150 are 60/150 calendar days out. Archive table is frozen; only the tape-side Wilson waits.
