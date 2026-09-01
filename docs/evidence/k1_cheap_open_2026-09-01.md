# K1 -- cheap D+1 rungs: do they settle YES often enough to pay?

Generated 2026-09-01T20:36:38Z

- Quote tape: `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`
- Settlement catalog: `/home/jon/.local/share/breezy/catalog`
- Regenerate: `python scripts/analysis/k1_cheap_open_settlement.py`

This is a DESCRIPTIVE settlement-frequency measurement plus a closed-form break-even comparison. No order, fill, position or P&L is simulated: Nautilus Trader is the exclusive owner of backtesting.

## 1. Tape preflight (L-8)

`ParquetDataCatalog._read_feather_file` swallows `(ArrowInvalid, OSError)` and returns `None`, which `convert_stream_to_data` turns into a silent `continue`. Every file below was opened DIRECTLY, so a truncated file is counted rather than read as an empty market. Both the `data/` and `live/` subtrees are read.

| Data class | Files | Parsed | FAILED (corrupt) | FAILED (mid-write) | Raw rows | Dedup rows | Instruments |
|---|---:|---:|---:|---:|---:|---:|---:|
| BinaryOption | 2 | 2 | 0 | 0 | 120 | 120 | 90 |
| OrderBookDepth10 | 280 | 276 | 0 | 4 | 250207 | 240119 | 65 |
| QuoteTick | 147 | 147 | 0 | 0 | 220940 | 213049 | 37 |

Capture is ONGOING while this script runs, so the newest feather in the active recorder run is routinely mid-message. Those are separated from genuine corruption by file mtime rather than pooled: a mid-write file reads cleanly on the next run, a corrupt one never will. Neither is swallowed.

Raw rows exceed dedup rows because the recorder writes each frame to the streaming `live/` feather AND the consolidated `data/` parquet; rows are de-duplicated on `(instrument_id, ts_event, ts_init)`.

### Parse failures -- OrderBookDepth10 (4)

- [MID_WRITE_SUSPECTED] `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/5a111bca-c349-49d7-94bc-948649485ac8/order_book_depths/tc-temp-mdwhigh-2026-09-01-gte93lt94f.POLYMARKET_US/tc-temp-mdwhigh-2026-09-01-gte93lt94f.POLYMARKET_US_1788272912394543098.feather`
  - ArrowInvalid: Expected to read 3160 metadata bytes, but only read 0
- [MID_WRITE_SUSPECTED] `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/5a111bca-c349-49d7-94bc-948649485ac8/order_book_depths/tc-temp-mdwhigh-2026-09-01-gte95f.POLYMARKET_US/tc-temp-mdwhigh-2026-09-01-gte95f.POLYMARKET_US_1788272912405024187.feather`
  - ArrowInvalid: Expected to read 3160 metadata bytes, but only read 0
- [MID_WRITE_SUSPECTED] `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/5a111bca-c349-49d7-94bc-948649485ac8/order_book_depths/tc-temp-sfohigh-2026-09-01-gte64lt65f.POLYMARKET_US/tc-temp-sfohigh-2026-09-01-gte64lt65f.POLYMARKET_US_1788272912551006131.feather`
  - ArrowInvalid: Expected to read 3160 metadata bytes, but only read 0
- [MID_WRITE_SUSPECTED] `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/5a111bca-c349-49d7-94bc-948649485ac8/order_book_depths/tc-temp-sfohigh-2026-09-01-gte66lt67f.POLYMARKET_US/tc-temp-sfohigh-2026-09-01-gte66lt67f.POLYMARKET_US_1788272912557194652.feather`
  - ArrowInvalid: Expected to read 3160 metadata bytes, but only read 0

**Observed tape span (ts_event):** 2026-08-30T10:06:37Z -> 2026-09-01T20:36:27Z

### Rows per instrument (deduplicated)

| Instrument | order_book_depths | quote_tick |
|---|---:|---:|
| `tc-temp-laxhigh-2026-08-31-gte72lt73f.POLYMARKET_US` | 1117 | 0 |
| `tc-temp-laxhigh-2026-08-31-gte74lt75f.POLYMARKET_US` | 1159 | 0 |
| `tc-temp-laxhigh-2026-08-31-gte76lt77f.POLYMARKET_US` | 1112 | 0 |
| `tc-temp-laxhigh-2026-08-31-gte78lt79f.POLYMARKET_US` | 1075 | 7 |
| `tc-temp-laxhigh-2026-08-31-gte80f.POLYMARKET_US` | 1519 | 115 |
| `tc-temp-laxhigh-2026-08-31-lt72f.POLYMARKET_US` | 1175 | 0 |
| `tc-temp-laxhigh-2026-09-01-gte76lt77f.POLYMARKET_US` | 25802 | 25788 |
| `tc-temp-laxhigh-2026-09-01-gte78lt79f.POLYMARKET_US` | 18017 | 17910 |
| `tc-temp-laxhigh-2026-09-01-gte80lt81f.POLYMARKET_US` | 2555 | 1637 |
| `tc-temp-laxhigh-2026-09-01-gte82lt83f.POLYMARKET_US` | 8400 | 2896 |
| `tc-temp-laxhigh-2026-09-01-gte84f.POLYMARKET_US` | 2260 | 1 |
| `tc-temp-laxhigh-2026-09-01-lt76f.POLYMARKET_US` | 24427 | 24374 |
| `tc-temp-mdwhigh-2026-08-31-gte89lt90f.POLYMARKET_US` | 1004 | 0 |
| `tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US` | 876 | 0 |
| `tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US` | 980 | 0 |
| `tc-temp-mdwhigh-2026-08-31-gte95lt96f.POLYMARKET_US` | 984 | 0 |
| `tc-temp-mdwhigh-2026-08-31-gte97f.POLYMARKET_US` | 983 | 0 |
| `tc-temp-mdwhigh-2026-08-31-lt89f.POLYMARKET_US` | 1009 | 0 |
| `tc-temp-mdwhigh-2026-09-01-gte87lt88f.POLYMARKET_US` | 2669 | 2361 |
| `tc-temp-mdwhigh-2026-09-01-gte89lt90f.POLYMARKET_US` | 8396 | 7781 |
| `tc-temp-mdwhigh-2026-09-01-gte91lt92f.POLYMARKET_US` | 13969 | 13444 |
| `tc-temp-mdwhigh-2026-09-01-gte93lt94f.POLYMARKET_US` | 6114 | 21870 |
| `tc-temp-mdwhigh-2026-09-01-gte95f.POLYMARKET_US` | 5495 | 22463 |
| `tc-temp-mdwhigh-2026-09-01-lt87f.POLYMARKET_US` | 3713 | 1223 |
| `tc-temp-miahigh-2026-08-30-gte89lt90f.POLYMARKET_US` | 127 | 127 |
| `tc-temp-miahigh-2026-08-30-gte91lt92f.POLYMARKET_US` | 144 | 144 |
| `tc-temp-miahigh-2026-08-31-gte87lt88f.POLYMARKET_US` | 486 | 0 |
| `tc-temp-miahigh-2026-08-31-gte89lt90f.POLYMARKET_US` | 488 | 0 |
| `tc-temp-miahigh-2026-08-31-gte91lt92f.POLYMARKET_US` | 500 | 0 |
| `tc-temp-miahigh-2026-08-31-gte93lt94f.POLYMARKET_US` | 451 | 0 |
| `tc-temp-miahigh-2026-08-31-gte95f.POLYMARKET_US` | 420 | 0 |
| `tc-temp-miahigh-2026-08-31-lt87f.POLYMARKET_US` | 489 | 0 |
| `tc-temp-miahigh-2026-09-01-gte87lt88f.POLYMARKET_US` | 5187 | 4967 |
| `tc-temp-miahigh-2026-09-01-gte89lt90f.POLYMARKET_US` | 7763 | 7629 |
| `tc-temp-miahigh-2026-09-01-gte91lt92f.POLYMARKET_US` | 7251 | 7126 |
| `tc-temp-miahigh-2026-09-01-gte93lt94f.POLYMARKET_US` | 13281 | 11832 |
| `tc-temp-miahigh-2026-09-01-gte95f.POLYMARKET_US` | 2210 | 1901 |
| `tc-temp-miahigh-2026-09-01-lt87f.POLYMARKET_US` | 8300 | 6473 |
| `tc-temp-nychigh-2026-08-30-gte82lt83f.POLYMARKET_US` | 164 | 164 |
| `tc-temp-nychigh-2026-08-30-gte84lt85f.POLYMARKET_US` | 86 | 86 |
| `tc-temp-nychigh-2026-08-30-lt82f.POLYMARKET_US` | 154 | 154 |
| `tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US` | 437 | 0 |
| `tc-temp-nychigh-2026-08-31-gte80lt81f.POLYMARKET_US` | 493 | 0 |
| `tc-temp-nychigh-2026-08-31-gte82lt83f.POLYMARKET_US` | 480 | 0 |
| `tc-temp-nychigh-2026-08-31-gte84lt85f.POLYMARKET_US` | 484 | 0 |
| `tc-temp-nychigh-2026-08-31-gte86f.POLYMARKET_US` | 478 | 0 |
| `tc-temp-nychigh-2026-08-31-lt78f.POLYMARKET_US` | 492 | 0 |
| `tc-temp-nychigh-2026-09-01-gte82lt83f.POLYMARKET_US` | 8546 | 7610 |
| `tc-temp-nychigh-2026-09-01-gte84lt85f.POLYMARKET_US` | 5818 | 4369 |
| `tc-temp-nychigh-2026-09-01-gte86lt87f.POLYMARKET_US` | 3950 | 888 |
| `tc-temp-nychigh-2026-09-01-gte88lt89f.POLYMARKET_US` | 5181 | 2205 |
| `tc-temp-nychigh-2026-09-01-gte90f.POLYMARKET_US` | 4899 | 204 |
| `tc-temp-nychigh-2026-09-01-lt82f.POLYMARKET_US` | 2217 | 2169 |
| `tc-temp-sfohigh-2026-08-31-gte64lt65f.POLYMARKET_US` | 1076 | 0 |
| `tc-temp-sfohigh-2026-08-31-gte66lt67f.POLYMARKET_US` | 958 | 0 |
| `tc-temp-sfohigh-2026-08-31-gte68lt69f.POLYMARKET_US` | 1257 | 0 |
| `tc-temp-sfohigh-2026-08-31-gte70lt71f.POLYMARKET_US` | 1071 | 0 |
| `tc-temp-sfohigh-2026-08-31-gte72f.POLYMARKET_US` | 1253 | 0 |
| `tc-temp-sfohigh-2026-08-31-lt64f.POLYMARKET_US` | 1255 | 0 |
| `tc-temp-sfohigh-2026-09-01-gte64lt65f.POLYMARKET_US` | 2958 | 2318 |
| `tc-temp-sfohigh-2026-09-01-gte66lt67f.POLYMARKET_US` | 2087 | 1337 |
| `tc-temp-sfohigh-2026-09-01-gte68lt69f.POLYMARKET_US` | 1301 | 1173 |
| `tc-temp-sfohigh-2026-09-01-gte70lt71f.POLYMARKET_US` | 4020 | 3113 |
| `tc-temp-sfohigh-2026-09-01-gte72f.POLYMARKET_US` | 2348 | 2056 |
| `tc-temp-sfohigh-2026-09-01-lt64f.POLYMARKET_US` | 4749 | 3134 |

`order_book_depths` covers 65 instruments against 37 in `quote_tick`. A `QuoteTick` is two-sided and `parse_book_top` refuses to invent a bid, so a market whose BID side is empty -- the normal state of a deep cheap offer here -- emits depth only. Reading quotes alone would drop exactly the population K1 measures.

## 2. Population as implemented

One member per `(station, climate_day, rung)` whose book carried a genuine ask STRICTLY before its climate day began in local STANDARD time (the registry's fixed `std_utc_offset_hours`, never DST-aware -- the same rule as `breezy.ingest.records._climate_day_end_ns`). The entry price is the FIRST such ask by `ts_event` ascending, ties broken on `ts_init`; never an average and never the best of the window.

Settlement truth is the NWS CLI integer `tmax_f` via `read_climate_day_including_corrections`, requiring `is_final`. No ASOS/METAR maximum is ever substituted. Predicate: gte{A}lt{B}f settles YES iff A <= observed_tmax_f <= B (both bounds INCLUSIVE); lt{N}f settles YES iff observed_tmax_f <= N-1; gte{N}f settles YES iff observed_tmax_f >= N. The slug's `lt` token is venue naming, not the settlement predicate. (evidence: `docs/evidence/venue/polymarket_us/THRESHOLD_SEMANTICS_2026-08-25.md:170-223`).

| Stage | Count |
|---|---:|
| Instruments recorded in the tape | 90 |
| Instruments with any ask observation | 61 |
| Dropped: no instrument definition record | 0 |
| Dropped: station not in registry | 0 |
| Dropped: no genuine ask before the climate day | 31 |
| **D+1 entries found** | **30** |
| Dropped: no CLI record for that station-day | 24 |
| Dropped: CLI record not FINAL (day still open) | 6 |
| Dropped: FINAL record has no `tmax_f` | 0 |
| **MEASURED POPULATION** | **0** |

### Capture coverage per station-day

A D+1 book exists only if the recorder was RUNNING before that station-day's local-standard midnight. `First observation` below is the earliest tape observation of ANY rung of that station-day; `Day began` is its local-standard midnight in UTC. Where the first observation falls after the day began, the entire station-day is intraday and contributes nothing to K1 -- by construction, not by defect.

| Station | Climate day | Day began (UTC) | First observation (UTC) | D+1? | Settlement |
|---|---|---|---|:--:|---|
| LAX | 2026-08-31 | 2026-08-31T08:00:00Z | 2026-09-01T00:40:55Z | no | n/a -- no D+1 entry |
| LAX | 2026-09-01 | 2026-09-01T08:00:00Z | 2026-09-01T00:41:04Z | YES | no CLI record yet (climate day not closed) |
| MDW | 2026-08-31 | 2026-08-31T06:00:00Z | 2026-09-01T00:40:42Z | no | n/a -- no D+1 entry |
| MDW | 2026-09-01 | 2026-09-01T06:00:00Z | 2026-09-01T00:40:43Z | YES | no CLI record yet (climate day not closed) |
| MIA | 2026-08-30 | 2026-08-30T05:00:00Z | 2026-08-30T16:05:40Z | no | n/a -- no D+1 entry |
| MIA | 2026-08-31 | 2026-08-31T05:00:00Z | 2026-09-01T00:40:59Z | no | n/a -- no D+1 entry |
| MIA | 2026-09-01 | 2026-09-01T05:00:00Z | 2026-09-01T00:41:00Z | YES | CLI record present but PRELIMINARY |
| NYC | 2026-08-30 | 2026-08-30T05:00:00Z | 2026-08-30T16:05:41Z | no | n/a -- no D+1 entry |
| NYC | 2026-08-31 | 2026-08-31T05:00:00Z | 2026-09-01T00:40:59Z | no | n/a -- no D+1 entry |
| NYC | 2026-09-01 | 2026-09-01T05:00:00Z | 2026-09-01T00:40:43Z | YES | no CLI record yet (climate day not closed) |
| SFO | 2026-08-31 | 2026-08-31T08:00:00Z | 2026-09-01T00:40:43Z | no | n/a -- no D+1 entry |
| SFO | 2026-09-01 | 2026-09-01T08:00:00Z | 2026-09-01T00:40:59Z | YES | no CLI record yet (climate day not closed) |

## 3. Entry-ask distribution (D+1 entries, all outcomes)

| Entry ask | Count |
|---:|---:|
| 0.01 | 1 |
| 0.02 | 4 |
| 0.03 | 1 |
| 0.04 | 1 |
| 0.05 | 1 |
| 0.06 | 1 |
| 0.09 | 2 |
| 0.13 | 1 |
| 0.15 | 2 |
| 0.16 | 2 |
| 0.18 | 1 |
| 0.21 | 2 |
| 0.26 | 1 |
| 0.27 | 1 |
| 0.28 | 1 |
| 0.29 | 1 |
| 0.33 | 3 |
| 0.37 | 1 |
| 0.51 | 1 |
| 0.53 | 1 |
| 0.54 | 1 |

Min 0.01, median 0.16, max 0.54, n=30.

## 4. Settlement frequency by station and cheap-ask stratum

Break-even is `ask + theta * ask * (1 - ask)` evaluated at the stratum THRESHOLD (the most expensive ask admitted), with `theta` read per market from `instrument.info[fee_coefficient]` -- never defaulted. `clears?` asks whether the Wilson 95% UPPER bound exceeds break-even.

### Per station (PRIMARY -- G-01: WFOs are not exchangeable)

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| _no station has a measured population_ | | | | | | | | | | |

### Pooled across stations (INDICATIVE ONLY)

G-01 established that WFOs are not exchangeable, so pooling mixes populations with different forecast skill and different climatology. Reported for scale only; it is not the finding.

| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | Break-even | Clears? | Resolution floor | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|
| POOLED | 0.01 | 0 | 0 | n/a | n/a | n/a | 0.010594 | - | n/a | UNDERPOWERED |
| POOLED | 0.02 | 0 | 0 | n/a | n/a | n/a | 0.021176 | - | n/a | UNDERPOWERED |
| POOLED | 0.03 | 0 | 0 | n/a | n/a | n/a | 0.031746 | - | n/a | UNDERPOWERED |
| POOLED | 0.05 | 0 | 0 | n/a | n/a | n/a | 0.052850 | - | n/a | UNDERPOWERED |

## 5. Power

To distinguish a true settle rate of 3% (a real edge at a 1c ask) from 1% (no edge) at 95% confidence -- i.e. for the Wilson 95% lower bound at 3% to clear 1% -- requires **n = 96** qualifying D+1 observations per cell.


That is only the DISCRIMINATION sample. The binding constraint on a FAMILY DEAD verdict is stricter: the Wilson 95% UPPER bound must fall to break-even even when NOTHING settles YES, and at zero events that bound is `z^2 / (n + z^2)`.

| Stratum (ask <=) | Break-even | n to discriminate 3% from 1% | n to REFUTE at zero YES |
|---:|---:|---:|---:|
| 0.01 | 0.010594 | 96 | 359 |
| 0.02 | 0.021176 | 96 | 178 |
| 0.03 | 0.031746 | 96 | 118 |
| 0.05 | 0.052850 | 96 | 69 |

The pooled sample currently reaches n = 0. A shortfall is a statement about how much capture has accumulated, not about the venue.

Capture yields roughly one D+1 book per station per day across 5 stations and 6 rungs per station-day, so n = 96 qualifying observations is on the order of 4 more full capture days IF every station-day is captured before its local midnight. Rungs within one station-day are NOT independent (they partition the same outcome), so the effective station-day requirement is materially larger than that arithmetic suggests -- treat it as a floor.

## 6. VERDICT

**UNDERPOWERED -- INCONCLUSIVE**

The measurement settles nothing yet. Capture began recently and is ongoing; the D+1 window (a rung's book observed before its own climate day starts) is the scarcest slice of it. n = 96 per cell is needed to discriminate 3% from 1%; the largest cell here is n = 0.

**30 D+1 entries are already captured and waiting only on settlement truth.** They belong to climate days that have not closed yet; they enter the population automatically on the next run after their FINAL CLI product is ingested. The measurement is wired end to end -- what is missing is elapsed time, not code.

Do NOT read this as evidence for or against the calibration family. Re-run this script as capture accumulates -- it is idempotent and takes the catalog path as an argument.


---

## 7. Coordinator addendum — when does K1 actually report? (2026-09-01)

§5 gives the required `n` per stratum but not the ARRIVAL RATE, and the two must
be crossed before K1 can be called a viable gate. Climate day 2026-09-01 yielded
exactly 30 D+1 rung-entries (5 stations x 6 rungs). Combining that with the §3
entry-ask distribution:

| Stratum (ask <=) | entries/day | n to refute at zero YES | calendar days |
|---:|---:|---:|---:|
| 0.01 | 1 | 359 | **359** |
| 0.02 | 5 | 178 | 36 |
| 0.03 | 6 | 118 | **20** |
| 0.05 | 8 | 69 | **9** |

**The 0.01 tick is effectively unrefutable** — roughly one qualifying D+1 entry
per day across the whole five-station universe means a zero-YES refutation would
take about a year. Any plan that waits for the 0.01 stratum to report is not a
plan.

**K1 is viable in the 0.03-0.05 band, on a 9-20 day horizon**, and viable in
BOTH directions there: at `ask <= 0.05` (break-even 0.052850) with n=69, a
realized pi around 11-12% would put the Wilson LOWER bound above break-even and
return FAMILY SURVIVES, while a pi at or near zero returns FAMILY DEAD. That is
the cell to run the gate in.

This also corrects a framing carried from the strategy design: the D+1 book is
**not** concentrated at the 1c floor. Observed entry asks are min 0.01, **median
0.16**, max 0.54 (n=30). The pre-event book prices a real distribution of
probabilities; the 1c-floor pile-up is a property of the POST-peak tape, which is
the population L-9's amendment excludes.

**Caveat on independence (open).** The n above treat rung-entries as independent.
They are not: the six rungs of one city-day are mutually exclusive, so exactly one
settles YES and the within-day count is capped at 1. Mutual exclusivity makes the
sum's variance SMALLER than the independent case, so Wilson is conservative here
rather than anti-conservative — but the honest reporting unit is the STATION-DAY
(5/day), not the rung. Before any verdict is declared, re-derive the interval on
station-days, or state explicitly that the rung-level interval is being used as a
conservative bound.

**Operational consequence, already actioned.** A D+1 book exists only if the
recorder is running before local midnight. Capture is now supervised to
2026-10-01 (detached, auto-restart, 50 GB disk floor), which covers the 9-20 day
window the 0.03-0.05 band needs. Re-run this script as capture accumulates; the
30 already-captured entries enter automatically once their FINAL CLI lands.
