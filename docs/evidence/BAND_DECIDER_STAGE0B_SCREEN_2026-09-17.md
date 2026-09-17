# STAGE 0b — adverse-selection screen

Unconditional `p_bound_band` (label = NWS CLI `settled_f`) vs 2026-09-16 YES-leg tape, first 90 min of 12:00–17:00 LST. Denominator = all spanning-band window minutes in the cell (outside-band rows kept). **STOP: 0.25–0.75 GATE FAIL** (point and Wilson). Plan §6/§7: do not start Stage 1.

## Data coverage

| station | IEM mo | missing | IEM days | CLI catalog | CLI AFOS | CLI merged | CLI∩IEM | scored |
|---|---:|---|---:|---|---|---|---:|---:|
| MIA | 69 | — | 1980 | 2026-08-17..2026-09-16 n=31 | 2021-01-01..2025-12-31 n=1813 | 2021-01-01..2026-09-16 n=1844 | 1753 | 1404 |
| LAX | 69 | — | 1889 | 2026-08-17..2026-09-16 n=31 | 2021-01-01..2025-12-31 n=1820 | 2021-01-01..2026-09-16 n=1851 | 1689 | 1212 |
| SFO | 67 | 2024-12,2025-01 | 1898 | 2026-08-17..2026-09-16 n=31 | 2021-01-01..2025-12-31 n=1799 | 2021-01-01..2026-09-16 n=1830 | 1648 | 1375 |
| MDW | 67 | 2025-04,2025-05 | 1925 | 2026-08-16..2026-09-16 n=32 | 2021-01-01..2025-12-31 n=1826 | 2021-01-01..2026-09-16 n=1858 | 1708 | 1371 |

MDW wait: 67/69 after 20 min (proceeded). Catalog parquet is ~1 month (live ingest); AFOS cache is the 2021–2025 study corpus (2026 AFOS zip absent, no network). Catalog tmax MIA 09-15=93, 09-16=92. IEM 09-16 **window absent** (files end before 12:00 LST).

## Band reimplementation

F→C half-up `floor((F−32)·5/9+0.5)` (choice: repo `temperature.py` only defines C→F half-up). 5-min: integer °C, precision 10, `is_metar=False`. :53: tenths °C half-up, precision 5, `is_metar=True`. Band = `RunningExtremeAccumulator.value_at`.

Unit vs 09-16 tape: 91F→33C→[91,92] MIA **match**; 78F→26C→[78,80] LAX **match**; 66F→19C→[65,67] SFO **match**. 09-16 archive replay: **gap**. 09-15 reconstructed `[lower,upper,exact]` at open / +90 min / close (CLI settled_f):

- MIA [91,92,None] / [93,94,None] / [93,94,None] settled=93 (log: live later collapsed via METAR; synthesis stayed integer-C)
- LAX [80,81,None] all three, settled=81
- SFO [73,74,None] all three, settled=73
- MDW [81,81,81] / [82,83,None] / [85,85,85] settled=85 (METAR collapsed to exact)

## 09-16 tape screen (`source=quote`, first 90 min, candidate rungs)

jsonl=53624 quote=26812 first90=20933 (ambiguous=20795, illegal_cell=138) scored=20795 missing_cell=0. Stations: MIA 4806, LAX 6051, SFO 9938, MDW 0. Ask buckets: `<0.25`, `0.25≤ask≤0.75`, `>0.75`. Wilson undefined if cell N<90 (here every scored row had N≥90).

| ask bucket | rows | frac margin>0 (point) | median margin (point) | GATE point | frac>0 (Wilson) | median Wilson | GATE Wilson |
|---|---:|---:|---:|---|---:|---:|---|
| <0.25 | 4295 | 1.0000 | +0.3178 | — | 1.0000 | +0.3031 | — |
| 0.25-0.75 | 3355 | 0.3246 | −0.2993 | **FAIL** | 0.3246 | −0.3134 | **FAIL** |
| >0.75 | 13145 | 0.0000 | −0.4706 | — | 0.0000 | −0.4852 | — |

GATE (need ≥20 rows, ≥50% margin>0, median≥0.03 in **0.25–0.75 only**): n=3355 OK; 32.46% pos **fail**; median −0.2993 **fail**. Cheap asks all clear (p≈0.4–0.5 vs ask<0.25); expensive asks never. Pooled numbers would mislead — this is why the gate is the mid bucket.

## Stage 2 preview (first 90 min spanning minutes)

`(station × band_width_f × m30)` cells with N≥90: **24/24 = 1.00** (widths {1,2} × m30 {0,30,60} × 4 stations). LOYO Brier of `p_hat` vs label (both candidates): **0.226587** on n=2,575,448 (years 2021–2026, skipped_no_train=0). CITL (LOYO mean p vs mean y):

| station | n | mean p | mean y | p−y |
|---|---:|---:|---:|---:|
| MIA | 698256 | 0.4568 | 0.4570 | −0.00015 |
| LAX | 626026 | 0.4383 | 0.4384 | −0.00012 |
| SFO | 635998 | 0.4026 | 0.4028 | −0.00020 |
| MDW | 615168 | 0.4269 | 0.4272 | −0.00027 |

## Top 10 cells by N (minutes; lower+upper share N)

| station | season | hour | width | m30 | N | p_lower | p_upper | outside |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| MIA | JJA | 16 | 1 | 270 | 6870 | 0.7074 | 0.2882 | 0.0044 |
| MIA | JJA | 14 | 1 | 150 | 6856 | 0.6698 | 0.3215 | 0.0088 |
| MIA | JJA | 13 | 1 | 90 | 6826 | 0.6046 | 0.3822 | 0.0132 |
| MIA | JJA | 16 | 1 | 240 | 6820 | 0.7060 | 0.2896 | 0.0044 |
| MIA | JJA | 15 | 1 | 180 | 6805 | 0.6951 | 0.3005 | 0.0044 |
| MIA | JJA | 15 | 1 | 210 | 6798 | 0.7020 | 0.2936 | 0.0044 |
| MIA | JJA | 14 | 1 | 120 | 6770 | 0.6603 | 0.3309 | 0.0089 |
| MIA | JJA | 13 | 1 | 60 | 6750 | 0.5481 | 0.4274 | 0.0244 |
| MIA | JJA | 12 | 1 | 30 | 6635 | 0.4739 | 0.4876 | 0.0386 |
| MIA | JJA | 12 | 1 | 0 | 6620 | 0.3860 | 0.5566 | 0.0574 |

## Choices / caveats

- Clock = **LST year-round** (`_local_hour`), not IANA DST. 12:00 LST in September = 13:00 LDT.
- 30-min bucket from **true** minutes since 12:00 LST (tape field is hour-truncated `(hour−12)×60`).
- Ladder: even-phase interiors `[2k,2k+1]`, assumed 6-rung list always contains both candidates. MDW 09-16 was odd-phase with gaps (zero YES tape rows).
- One tape day. IEM 09-16 window missing. Sampled 5-min maxima biased low vs continuous peaks (plan §1). Peak RSS 305 MB.

## Reproduce

```
STAGE0B_SKIP_MDW_WAIT=1 /home/jon/breezy/.venv/bin/python \
  /tmp/claude-1000/-home-jon-breezy/0d7dc236-f8bc-46ae-8418-026805446111/scratchpad/stage0b/stage0b_screen.py
```

Omit `STAGE0B_SKIP_MDW_WAIT` to poll MDW to 69 months (60 s, ≤20 min). Inputs: `.../scratchpad/iem1min/<STA>/*.csv`; catalog `~/.local/share/breezy/catalog/polymarket_us/<STA>/data/custom_nws_climate_day/`; AFOS `~/.local/share/breezy/archive/settlement-alignment-cache/`; tape `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_2026-09-16.jsonl`. Outputs in this directory: `p_bound_band_table.csv`, `tape_bucket_summary.json`, `stage2_preview.json`, `verify.json`, this report.
