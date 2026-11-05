# LADDER_EV — afternoon-covered listed station-day census (converted tape, 2026-09-07)

Purpose: the C12 pre-check of `docs/strategies/breezy_strategy_ladder_ev_2026-09-07.md` §12 —
is the structural-dead branch of the design-kill script reachable on the tape that exists?
Read-only measurement over `~/.local/share/breezy/catalog/quote_tape/polymarket_us/data/`
(converted parquet only; `live/` not opened, L-20 applies). Script:
`scripts/analysis/ladder_ev_afternoon_coverage_census.py` (wall 10.8 s, RSS 226 MiB).

**Result: train window (08-30..09-04) = 7 covered family station-days; holdout (09-05, 09-06) = 4;
total 11. The 15-day floor is NOT reached ⇒ the §12 structural-dead branch is UNREACHABLE today
and any run of the kill script returns INSUFFICIENT DATA, not KILL.** NYC excluded (3 more if counted).
09-06 is listed for all five stations but carries zero afternoon Depth10 frames in the converted tape
(files end 06:58Z 09-06; the recorder was a zombie after the 09:00Z rotate — GL-12).

Rule applied (cited by the investigator): COVERED = span of distinct Depth10 `ts_event` instants
inside `[12:00, 17:00)` LST ≥ 30 min, union across the six HIGH rungs, offsets from
`registry/sites.toml` (LAX/SFO −8, MDW −6, MIA/NYC −5, never DST), matching
`scripts/analysis/ma_prelock_winner_ask_study.py:306-361` and PREREG v2 §9 line 213.

## 1. Station × climate_day (Depth10)

`frames` = row count in window; `min_bk` = distinct LST minute buckets (reporting only); `span` = COVERED quantity (minutes). First/last are LST.

| stn | day | listed | frames | min_bk | span | first | last | COVERED |
|---|---|---:|---:|---:|---:|---|---|---|
| LAX | 08-30 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| LAX | 08-31 | 6 | 449 | 20 | 19.0 | 16:40:55 | 16:59:52 | no |
| LAX | 09-01 | 6 | 9079 | 300 | 299.9 | 12:00:00 | 16:59:55 | **YES** |
| LAX | 09-02 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| LAX | 09-03 | 6 | 0 | 0 | 0.0 | — | — | no |
| LAX | 09-04 | 6 | 2007 | 14 | 14.0 | 12:00:00 | 12:13:58 | no |
| LAX | 09-05 | 6 | 640 | 23 | 289.5 | 12:09:30 | 16:58:57 | **YES** |
| LAX | 09-06 | 6 | 0 | 0 | 0.0 | — | — | no |
| SFO | 08-30 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| SFO | 08-31 | 6 | 391 | 19 | 19.0 | 16:40:43 | 16:59:45 | no |
| SFO | 09-01 | 6 | 5723 | 300 | 299.9 | 12:00:01 | 16:59:54 | **YES** |
| SFO | 09-02 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| SFO | 09-03 | 6 | 14879 | 151 | 150.5 | 12:00:00 | 14:30:33 | **YES** |
| SFO | 09-04 | 6 | 2419 | 14 | 14.0 | 12:00:00 | 12:13:59 | no |
| SFO | 09-05 | 6 | 652 | 18 | 289.2 | 12:09:06 | 16:58:20 | **YES** |
| SFO | 09-06 | 6 | 0 | 0 | 0.0 | — | — | no |
| MDW | 08-30 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| MDW | 08-31 | 6 | 0 | 0 | 0.0 | — | — | no |
| MDW | 09-01 | 6 | 33475 | 300 | 300.0 | 12:00:00 | 16:59:58 | **YES** |
| MDW | 09-02 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| MDW | 09-03 | 6 | 0 | 0 | 0.0 | — | — | no |
| MDW | 09-04 | 6 | 49226 | 134 | 134.0 | 12:00:00 | 14:13:58 | **YES** |
| MDW | 09-05 | 6 | 610 | 16 | 123.9 | 14:09:30 | 16:13:25 | **YES** |
| MDW | 09-06 | 6 | 0 | 0 | 0.0 | — | — | no |
| MIA | 08-30 | 2 | 0 | 0 | 0.0 | — | — | no |
| MIA | 08-31 | 6 | 0 | 0 | 0.0 | — | — | no |
| MIA | 09-01 | 6 | 4921 | 300 | 299.9 | 12:00:05 | 16:59:57 | **YES** |
| MIA | 09-02 | 0 | 0 | 0 | 0.0 | — | — | no (unlisted) |
| MIA | 09-03 | 6 | 0 | 0 | 0.0 | — | — | no |
| MIA | 09-04 | 6 | 6768 | 194 | 193.8 | 12:00:00 | 15:13:48 | **YES** |
| MIA | 09-05 | 6 | 7091 | 49 | 230.9 | 12:00:00 | 15:50:54 | **YES** |
| MIA | 09-06 | 6 | 0 | 0 | 0.0 | — | — | no |
| NYC | 08-30 | 3 | 0 | 0 | 0.0 | — | — | no **EXCL** |
| NYC | 08-31 | 6 | 0 | 0 | 0.0 | — | — | no **EXCL** |
| NYC | 09-01 | 6 | 9668 | 300 | 299.9 | 12:00:02 | 16:59:56 | YES **EXCL** |
| NYC | 09-02 | 0 | 0 | 0 | 0.0 | — | — | no **EXCL** unlisted |
| NYC | 09-03 | 6 | 0 | 0 | 0.0 | — | — | no **EXCL** |
| NYC | 09-04 | 6 | 15300 | 195 | 193.9 | 12:00:04 | 15:14:00 | YES **EXCL** |
| NYC | 09-05 | 6 | 4537 | 57 | 230.8 | 12:00:04 | 15:50:52 | YES **EXCL** |
| NYC | 09-06 | 6 | 0 | 0 | 0.0 | — | — | no **EXCL** |

## 2. Totals (4 non-NYC)

| Split | Covered station-days | Days |
|---|---:|---|
| Train 08-30..09-04 | **7** | LAX 09-01; SFO 09-01, 09-03; MDW 09-01, 09-04; MIA 09-01, 09-04 |
| Holdout 09-05, 09-06 | **4** | LAX/SFO/MDW/MIA 09-05; **none on 09-06** |
| All family in range | **11** | |
| train ≥ 15? | **no** (7 < 15) | `MIN_AFTERNOON_STATION_DAYS=15` at `ma_prelock…:163`; PREREG `:217` |

NYC (excluded): 3 covered (09-01, 09-04, 09-05). Distinct-minute buckets are **not** the COVERED predicate: LAX 09-05 has 23 minute buckets but span 289.5 → COVERED.

## 3. Rung snapshot (covered days; nearest **in-window** frame per rung)

Best ask/size skip size-0 pad (`src/breezy/strategy/depth10.py:31-41`). `*` = ask ∈ (0.05, 0.95) and size ≥ 1 (`ma_prelock…:153-154,166`). Δ = frame minus 13:00/15:00 LST (minutes). `n*` = count of `*`.

- **LAX 09-01** 13:00 n*=0: 76-77=0.95/200(−31.5); 78-79=0.03/2150(−31.5); 80-81=0.01/1.47e4(+0.1); 82-83=0.01/5781(−31.6); 84+=0.01/6.79e4(+0.1); <76=0.02/0.07(+0.1)
- **LAX 09-01** 15:00 n*=0: 76-77=0.95/200(−151.5); 78-79=0.03/2150(−151.5); 80-81=0.01/1.38e4(+0.1); 82-83=0.01/5781(−151.6); 84+=0.01/6.78e4(+0.1); <76=0.02/3.61e4(+0.1)
- **LAX 09-05** 13:00 n*=1: 73-74=0.01/4.16e4(−9.5); 75-76=0.01/4.88e4(−12.3); 77-78=0.03/509(−9.1); **79-80=0.22/1\*** (−9.4); 81+=0.99/1(−9.3); <73=0.01/4.78e4(−9.2)
- **LAX 09-05** 15:00 n*=2: 73-74=0.01/3.41e4(−46.9); 75-76=0.01/1.42e4(−48.0); **77-78=0.07/30\*** (−46.7); **79-80=0.54/47.62\*** (−47.5); 81+=NA; <73=0.01/1.93e4(−47.0)
- **SFO 09-01** 13:00 n*=2: 64-65=0.01/7.80e5(−0.2); 66-67=0.01/7.90e5(−0.1); 68-69=0.01/3.02e5(−0.1); **70-71=0.7/13\*** (−31.5); **72+=0.9/25\*** (−0.1); <64=0.01/8.47e5(−0.2)
- **SFO 09-01** 15:00 n*=2: 64-65=0.01/6.49e5(+0.1); 66-67=0.01/6.55e5(+0.1); 68-69=0.01/5.07e5(+0.1); **70-71=0.7/13\*** (−151.5); **72+=0.91/25\*** (+0.1); <64=0.01/7.23e5(+0.1)
- **SFO 09-03** 13:00 n*=1: 66-67=NA; 68-69=NA; 70-71=0.07/0.1(+0.0); **72-73=0.82/25\*** (+0.0); 74+=0.09/0.1(+0.0); <66=NA
- **SFO 09-03** 15:00 n*=2: 66-67=NA; 68-69=NA; **70-71=0.24/74\*** (−29.4); **72-73=0.78/37.26\*** (−29.5); 74+=0.03/150.2(−29.5); <66=NA
- **SFO 09-05** 13:00 n*=4: 67-68=0.02/60(−14.1); **69-70=0.17/10.18\***; **71-72=0.6/2.74\***; **73-74=0.28/1\***; **75+=0.6/25\*** (Δ~−9.1); <67=0.01/0.85
- **SFO 09-05** 15:00 n*=3: 67-68=0.02/18(−47.6); **69-70=0.38/3.42\***; 71-72=0.99/1; **73-74=0.6/25\***; **75+=0.6/25\*** (Δ~−47); <67=0.01/0.85
- **MDW 09-01** 13:00 n*=2: 87-88=0.01/8.15e5(+88.2); 89-90=0.01/9.10e4(+0.1); 91-92=0.01/1.04e4(+0.1); **93-94=0.59/40\***; **95+=0.48/44\***; <87=0.01/2.54e5(+0.1)
- **MDW 09-01** 15:00 n*=2: 87-88=0.01/8.15e5(−0.2); 89-90=0.01/8.20e5(−0.2); 91-92=0.01/4.36e5(−0.2); **93-94=0.84/208\***; **95+=0.22/75\***; <87=0.01/2.54e5(−31.8)
- **MDW 09-04** 13:00 n*=3: 89-90=0.01/1.20e4(−0.1); **91-92=0.14/68\***; **93-94=0.54/8\***; 95-96=0.37/0.1; **97+=0.07/50\***; <89=0.01/4.65e4
- **MDW 09-04** 15:00 n*=3: 89-90=0.01/5.58e4(−46.3); 91-92=0.14/0.1(−46.1); **93-94=0.74/45\***; **95-96=0.1/1\***; **97+=0.06/24\***; <89=0.01/3.11e5
- **MDW 09-05** 13:00 n*=3: **83-84=0.56/1\*** (+69.5); **85-86=0.18/155.2\*** (+69.8); 87-88=0.02/4(+72.8); 89-90=0.02/5(+75.2); 91+=0.01/1424(+109.7); **<83=0.25/1.1\*** (+71.9)
- **MDW 09-05** 15:00 n*=4: 83-84=0.98/1(−9.1); **85-86=0.19/24\***; **87-88=0.6/25\***; **89-90=0.07/831\***; 91+=0.01/1424; **<83=0.27/5\***
- **MIA 09-01** 13:00 n*=0: 87-88=0.01/3.66e5(+148.1); 89-90=NA; 91-92=0.04/217(+148.1); 93-94=0.01/150(0.0); 95+=0.01/1434(+148.1); <87=0.01/1.12e4(0.0)
- **MIA 09-01** 15:00 n*=0: 87-88=0.01/3.66e5(+28.1); 89-90=NA; 91-92=0.04/217(+28.1); 93-94=0.01/150(−0.1); 95+=0.01/1434(+28.1); <87=0.01/1.12e4(−0.2)
- **MIA 09-04** 13:00 n*=1: 87-88=0.01/5.74e5; 89-90=0.01/4.62e4; 91-92=0.98/89; **93-94=0.08/87\***; 95+=0.01/3.53e4; <87=0.01/1.17e6 (Δ~0)
- **MIA 09-04** 15:00 n*=0: 87-88=0.01/5.63e5; 89-90=0.01/2.45e5; 91-92=NA; 93-94=0.02/5424; 95+=0.01/3.98e4; <87=0.01/1.46e6 (Δ~−0.1)
- **MIA 09-05** 13:00 n*=2: 86-87=0.01/2.94e5(−23.8); 88-89=0.01/5.02e4(−24.6); **90-91=0.39/1\*** (−21.8); **92-93=0.65/87\*** (−21.9); 94+=0.02/881; <86=0.01/3.12e5
- **MIA 09-05** 15:00 n*=2: 86-87=0.01/2.94e5(+29.9); 88-89=0.01/5.02e4(+37.8); **90-91=0.39/1\*** (+14.5); **92-93=0.76/57\*** (+22.2); 94+=0.02/858(+32.4); <86=0.01/3.12e5(+45.6)
- **NYC 09-01 EXCL** 13:00 n*=2: **82-83=0.1/1\***; 84-85=0.01/16.56; 86-87=0.04/140; 88-89=0.03/6; 90+=0.01/599; **<82=0.66/216.8\*** (+148.1)
- **NYC 09-01 EXCL** 15:00 n*=2: **82-83=0.53/6\***; 84-85=0.03/7; 86-87=0.04/140; 88-89=0.03/6; 90+=0.01/410; **<82=0.66/216.8\*** (+28.1)
- **NYC 09-04 EXCL** 13:00 n*=2: 82-83=0.01/3.96e4; **84-85=0.85/25\***; **86-87=0.16/466.4\***; 88-89=0.01/1.54e4; 90+=0.01/1.03e5; <82=0.01/9.08e5
- **NYC 09-04 EXCL** 15:00 n*=0: 82-83=0.01/4.46e5; 84-85=0.97/7; 86-87=0.05/258; 88-89=0.01/1.54e4; 90+=0.01/1.03e5; <82=0.01/1.51e6
- **NYC 09-05 EXCL** 13:00 n*=2: **79-80=0.35/226\***; 81-82=0.04/3192; 83-84=0.03/2137; 85-86=0.01/7163; 87+=0.01/9143; **<79=0.66/1\*** (Δ~−22)
- **NYC 09-05 EXCL** 15:00 n*=2: **79-80=0.35/1\*** (+16.9); 81-82=0.04/2807(+9.5); 83-84=0.03/2087; 85-86=0.01/7163; 87+=0.01/9142; **<79=0.66/1\*** (+9.5)

## 4. Method

- Script: `/tmp/claude-1000/-home-jon-breezy/5c894742-38f5-41f8-b19f-38988342b4c3/scratchpad/coverage/census_afternoon_coverage.py`
- Command: `uv run python <script>` with `UV_CACHE_DIR` under that scratchpad (default `~/.cache/uv` was unwritable). Catalog read-only; `live/` not opened.
- Runtime: wall **10.77 s**; self `perf_counter` **10.587 s**; RSS **226.3 MiB** (`/usr/bin/time -v` max RSS 231768 kB).
- Reader: pyarrow on `data/order_book_depths/` (`ts_event` uint64 ns; Price/Qty = le-i128 / `FIXED_SCALAR` 1e16, checked against `ParquetDataCatalog` on one file). `data/quote_tick/` scanned for the same high dirs; COVERED stays Depth10-only (matches cited `collect_window_instants`).
- 09-06 zero-window check: LAX 09-06 dirs exist (6); parquet `ts_event` max `2026-09-06T06:58:17Z` = 22:58 LST 09-05, before 09-06 12:00 LST (20:00Z). Same pattern MDW (max 07:12Z). Not a filename-skip miss.
- 09-03 LAX listed but 0 window frames: capture gap across 20:00Z 09-03..01:00Z 09-04 (files end 09:00Z 09-03 then resume 05:15Z 09-04).

## Gaps / NOT ESTABLISHED

- Whether 09-02 (no dirs for any station) is a venue skip-day vs a capture hole — tape absence only; no venue listing payload was read.
- Whether later conversion will add 09-06 afternoon frames — current converted tape does not have them.
- Union of quote_tick ∪ Depth10 as COVERED: **not applied**. Spec text says “Depth10/quote” (`PREREG:213`) but the cited implementation is Depth10-only. Quote-tick span on near-miss days (LAX/SFO 08-31, 09-04) is ≤19 min and would not flip COVERED; SFO 09-03 has Depth10 coverage but 0 quote_tick window frames.
- “Nearest frame” is per-rung among that rung’s in-window Depth10 rows, not a synchronized cross-rung book at 13:00/15:00. Large |Δ| (e.g. MIA 09-01 +148 min, MDW 09-05 13:00 +69 min) means that rung had no frame near the clock.
- Polars was not used (pyarrow sufficient). `live/` contents NOT ESTABLISHED (not opened, per brief).

