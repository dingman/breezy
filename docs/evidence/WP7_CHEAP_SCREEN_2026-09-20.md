# WP-7 -- pre-registered economic cheap screen (2026-09-20)

**Overall: INSUFFICIENT-DATA**

Governed by `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`. Every parameter here is a copy of a pinned value in that document. Per §1(iv) EVERY attempted variant's table appears below, including INSUFFICIENT-DATA ones. Per §2.0 the bar is read on the WINDOW-POOLED cell only; the per-hour tables are diagnosis and are structurally barred from selecting a winner.

## Corpus census (measured, before any verdict)

- venue station-days on the depth tape (4-station pool): **81**
- depth files read: 2767; L0 rows streamed: 9642117
- station-days with NWS CLI settlement truth: **73**
- station-days with an NBS forecast: **0**
- station-days EXCLUDED as an incomplete join (no forecast and/or no settlement truth, so no decision exists to score): **81**
- DENOMINATOR NOTE: `n` below counts station-days with a COMPLETE join, take or no-take. §2.3 reads as though `n` were the with-a-would-take subset; §3's `> 50% of trials have post-fee margin > 0` is vacuous under that reading (every take has margin > 0 by the `min_edge > 0` rule), so the complete-join denominator is used and the take-only median is reported beside it. Flagged to the strategy lead as a registration ambiguity.

- FROZEN 0b error model fitted on 5808 TRAIN station-days (2021-01-01..2024-12-31); sigma is NOT re-fitted here (§2.2 amendment A4).
- FORECAST ARCHIVE ABSENT for KLAX 2026: ArchiveCacheMissingPayloadError
- FORECAST ARCHIVE ABSENT for KMDW 2026: ArchiveCacheMissingPayloadError
- FORECAST ARCHIVE ABSENT for KMIA 2026: ArchiveCacheMissingPayloadError
- FORECAST ARCHIVE ABSENT for KSFO 2026: ArchiveCacheMissingPayloadError
- CORPUS DISJOINT -- the registration's §2.3 inventory does not reproduce. The venue price tape and the NBS forecast archive DO NOT OVERLAP: the archive's last runtime is 2025-12-31 19:00Z (4 stations x 5 station-years, 2021..2025) and the depth tape begins 2026-08-30. §2.3 records the triple overlap as n = 73 station-days; the number measured here as 73 is the venue-tape x SETTLEMENT-TRUTH overlap, with the FORECAST leg absent entirely. The economic screen therefore has no priceable station-day, which is a corpus gap (§4: extend the corpus), NOT a finding about the forecast thesis.

## All twelve variant tables (§1(iv))

| variant | n | takes | % positive margin | median margin | no_bid_side rate | Holm p | Holm threshold | verdict |
|---|---|---|---|---|---|---|---|---|
| `A1-B1-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00417 | **INSUFFICIENT-DATA** |
| `A1-B1-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00455 | **INSUFFICIENT-DATA** |
| `A1-B2-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00500 | **INSUFFICIENT-DATA** |
| `A1-B2-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00556 | **INSUFFICIENT-DATA** |
| `A2-B1-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00625 | **INSUFFICIENT-DATA** |
| `A2-B1-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00714 | **INSUFFICIENT-DATA** |
| `A2-B2-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.00833 | **INSUFFICIENT-DATA** |
| `A2-B2-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.01000 | **INSUFFICIENT-DATA** |
| `A3-B1-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.01250 | **INSUFFICIENT-DATA** |
| `A3-B1-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.01667 | **INSUFFICIENT-DATA** |
| `A3-B2-C1` | 0 | 0 | -- | -- | -- | 1.00000 | 0.02500 | **INSUFFICIENT-DATA** |
| `A3-B2-C2` | 0 | 0 | -- | -- | -- | 1.00000 | 0.05000 | **INSUFFICIENT-DATA** |

### Why each cell landed where it did

- `A1-B1-C1`: n=0 station-days is below the pre-registered floor of 20
- `A1-B1-C2`: n=0 station-days is below the pre-registered floor of 20
- `A1-B2-C1`: n=0 station-days is below the pre-registered floor of 20
- `A1-B2-C2`: n=0 station-days is below the pre-registered floor of 20
- `A2-B1-C1`: n=0 station-days is below the pre-registered floor of 20
- `A2-B1-C2`: n=0 station-days is below the pre-registered floor of 20
- `A2-B2-C1`: n=0 station-days is below the pre-registered floor of 20
- `A2-B2-C2`: n=0 station-days is below the pre-registered floor of 20
- `A3-B1-C1`: n=0 station-days is below the pre-registered floor of 20
- `A3-B1-C2`: n=0 station-days is below the pre-registered floor of 20
- `A3-B2-C1`: n=0 station-days is below the pre-registered floor of 20
- `A3-B2-C2`: n=0 station-days is below the pre-registered floor of 20

### Bootstrap intervals on the median post-fee margin

Date is the single PRIMARY and DECISIONAL cluster (§2.2). The station-clustered interval is sensitivity only and is explicitly non-decisional.

| variant | 95% CI (date, DECISIONAL) | 95% CI (station, sensitivity only) |
|---|---|---|
| `A1-B1-C1` | -- | -- |
| `A1-B1-C2` | -- | -- |
| `A1-B2-C1` | -- | -- |
| `A1-B2-C2` | -- | -- |
| `A2-B1-C1` | -- | -- |
| `A2-B1-C2` | -- | -- |
| `A2-B2-C1` | -- | -- |
| `A2-B2-C2` | -- | -- |
| `A3-B1-C1` | -- | -- |
| `A3-B1-C2` | -- | -- |
| `A3-B2-C1` | -- | -- |
| `A3-B2-C2` | -- | -- |

### Per-hour tables -- DIAGNOSIS ONLY, never a selection surface (§2.0)

| variant | hour LST | n | takes |
|---|---|---|---|
| `A1-B1-C1` | 9 | 0 | 0 |
| `A1-B1-C1` | 10 | 0 | 0 |
| `A1-B1-C1` | 11 | 0 | 0 |
| `A1-B1-C2` | 9 | 0 | 0 |
| `A1-B1-C2` | 10 | 0 | 0 |
| `A1-B1-C2` | 11 | 0 | 0 |
| `A1-B2-C1` | 9 | 0 | 0 |
| `A1-B2-C1` | 10 | 0 | 0 |
| `A1-B2-C1` | 11 | 0 | 0 |
| `A1-B2-C2` | 9 | 0 | 0 |
| `A1-B2-C2` | 10 | 0 | 0 |
| `A1-B2-C2` | 11 | 0 | 0 |
| `A2-B1-C1` | 12 | 0 | 0 |
| `A2-B1-C1` | 13 | 0 | 0 |
| `A2-B1-C1` | 14 | 0 | 0 |
| `A2-B1-C1` | 15 | 0 | 0 |
| `A2-B1-C1` | 16 | 0 | 0 |
| `A2-B1-C2` | 12 | 0 | 0 |
| `A2-B1-C2` | 13 | 0 | 0 |
| `A2-B1-C2` | 14 | 0 | 0 |
| `A2-B1-C2` | 15 | 0 | 0 |
| `A2-B1-C2` | 16 | 0 | 0 |
| `A2-B2-C1` | 12 | 0 | 0 |
| `A2-B2-C1` | 13 | 0 | 0 |
| `A2-B2-C1` | 14 | 0 | 0 |
| `A2-B2-C1` | 15 | 0 | 0 |
| `A2-B2-C1` | 16 | 0 | 0 |
| `A2-B2-C2` | 12 | 0 | 0 |
| `A2-B2-C2` | 13 | 0 | 0 |
| `A2-B2-C2` | 14 | 0 | 0 |
| `A2-B2-C2` | 15 | 0 | 0 |
| `A2-B2-C2` | 16 | 0 | 0 |
| `A3-B1-C1` | 10 | 0 | 0 |
| `A3-B1-C2` | 10 | 0 | 0 |
| `A3-B2-C1` | 10 | 0 | 0 |
| `A3-B2-C2` | 10 | 0 | 0 |

## Multiplicity (§1(ii))

Holm-Bonferroni across the ENTIRE enumerated set, `K_variants = 12`, family-wise `alpha = 0.05` one-sided, applied to the SELECTION decision. Cells below the n floor carry `p = 1.0` rather than being dropped, so the family stays at 12 and thin cells cannot inflate power.

Rejections at FWER 0.05: NONE

## §4 disposition

**INSUFFICIENT-DATA.** Under §4, INSUFFICIENT-DATA is an instruction to extend the corpus or the shadow period. It is never a PASS and never a KILL, and this run exits 0.
