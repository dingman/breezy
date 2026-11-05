# Paper replay — `current_rung_hold` mechanism test (2026-09-04)

**PROVENANCE: paper_replay — mechanism test only, NOT the live_small evidence
family. NO VERDICT.** n=4 station-days cannot reach the PREREG v1 floors
(kill n≥60, survive n≥150). Nothing here is an ROI inference; every number
below was printed by `scripts/analysis/current_rung_hold_paper_replay.py`
at branch tips `8aaff91`/`35a0049` (driver fixes `ed35e37`, `56abfcc`, `27c6910`,
`8aaff91`; strategy `4ffcbbb`).

## Inputs

- Tape: recorder instance `5a111bca-c349-49d7-94bc-948649485ac8` under
  `~/.local/share/breezy/catalog/quote_tape/polymarket_us` — the ONE instance
  holding every [12:00,17:00) LST quote for all four stations on 2026-09-01
  (coverage survey, 2026-09-04: LAX 5398, MDW 30151, MIA 1919, SFO 1244
  in-window quotes; SFO covers 300/300 minutes). An earlier 12-run sweep on
  instance `7dc3d1c0…` (span 19:30→05:47 LST) evaluated zero in-window quotes;
  the driver now refuses such a tape (`NoDecisionWindowCoverageError`).
- Observations: real IEM ASOS series from the settlement-alignment cache;
  `received = observed + lag` (PREREG A1 live rule). Lags 30 and 45 min.
- Closes: none recorded on any instrument; synthesized after the last tick
  with cosmetic price, economics from the FINAL climate day (`nws_final`).
- Precision arms `nws_integer_c` and `archive_metar` gave identical results
  in every run.

## Results (8 runs)

| station | lag | strategy refusals (counted) | wait-state diagnostics | scored |
|---|---|---|---|---|
| SFO | 30 | `edge_below_break_even` 1; outside_window 1152 | — | 0 |
| MDW | 30 | outside_window 25069 | not_executable 369; rung_not_current 2560 | **1** |
| MIA | 30 | outside_window 8342 | not_executable 1917; rung_not_current 2 | 0 |
| LAX | 30 | `illegal_cell` 1; outside_window 43706 | not_executable 11 | 0 |
| SFO | 45 | `observation_unavailable` 1; outside_window 1152 | — | 0 |
| MDW | 45 | `observation_unavailable` 1; outside_window 25069 | not_executable 581; rung_not_current 3258 | 0 |
| MIA | 45 | outside_window 8342 | not_executable 1917; rung_not_current 2 | 0 |
| LAX | 45 | `observation_unavailable` 1; outside_window 43706 | not_executable 11 | 0 |

The one scored trial (MDW 2026-09-01, lag 30, `tc-temp-mdwhigh-2026-09-01-gte91lt92f`):
`entry_ask=0.06 fill_px=0.06 fee=0.00 slippage=0.00 held=False
settlement_tmax_f=94 pnl=-0.06 settlement_basis=nws_final`. Wilson hold
interval [0.0000, 0.7935] (n=1). `BCa: n<30 — bound not computed`.

The lag-45 arms above ran under the rev 2 bound `stale_observation_hours=0.75`
(45 min): receipt = observed + 45 made every observation fresh for one
nanosecond, so every arm refused `observation_unavailable`. Grok ruled (A) in
`grok_live_small_spec_rev3_delta_2026-09-04.md`: the bound gives, pinned at
50 min (max live lag 45 + 5-min cadence), integer-minute nanoseconds, both
arms kept, archive table unchanged (`35a0049`). Re-run of the four lag-45
arms at branch tip `35a0049`:

| station | lag | strategy refusals (counted) | wait-state diagnostics | scored |
|---|---|---|---|---|
| SFO | 45 | `observation_unavailable` 1; outside_window 1152 | — | 0 |
| MDW | 45 | outside_window 25069 | not_executable 581; rung_not_current 3258 | **1** (same trial: entry 0.06, fill 0.06, not held, pnl −0.06) |
| MIA | 45 | outside_window 8342 | not_executable 1917; rung_not_current 2 | 0 |
| LAX | 45 | `illegal_cell` 1; outside_window 43706 | not_executable 11 | 0 |

SFO's remaining refusal is a genuinely stale running max at its first
executable snapshot (age > 50 min), counted as the spec requires.

## What the mechanism test caught (all fixed, all gated)

1. Driver discarded the strategy's refusal counters and printed the 6c
   scorer's refusals under the same word (`ed35e37`).
2. Driver converted instrument definitions through the disjoint-checked
   native path; re-emitted definitions broke every multi-file instance
   (`56abfcc`, reuses the ingest CLI's row-wise path with a target catalog).
3. `entry_ask` was the tape's FIRST quote (0.15 at 08:28 LST), not the
   decision ask the latch recorded (0.06); a quote and its own depth snapshot
   share `ts_init`, so the IOC crossed the previous snapshot and filled at a
   removed 0.04 level. Reported as slippage −0.11 "favourable". Fixed: entry
   ask from the latch, depth applied before quote at equal `ts_init`,
   `ImpossibleFillPriceError` guard on `fill_px < entry_ask` (`8aaff91`,
   Nautilus stable sort `backtest/engine.pyx:899`). Lesson L-25.
4. Strategy `subscribe_data` lacked `client_id` (Nautilus logged an ERROR on
   every start; the msgbus subscription still happened by accident,
   `common/actor.pyx:1258-1313`); wait-state diagnostics added (`4ffcbbb`).

## Recorder incident found by the coverage survey

2026-09-03 22:30 UTC OOM-kill → restart → websocket `_connect` failed →
Nautilus `DataEngine.check_connected() == False` then `TradingNode: RUNNING`
→ 6.7 h alive with zero quote ticks (all of 2026-09-04's windows lost;
instance `887d2005` quarantined as truncated, holding the only 09-03
in-window quotes). Restarted via systemctl 05:15 UTC, capturing within 90 s.
Fix `6fcadae`: a connect failure now routes through the existing fatal-fault
latch and exits non-zero so `Restart=always` applies; live at the next
rotate (09:00 UTC). Open: no `MemoryHigh` on the unit; truncated-instance
quarantine loses a whole day's in-window quotes.
