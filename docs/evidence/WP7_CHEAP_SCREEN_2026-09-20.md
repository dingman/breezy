# WP-7 -- pre-registered economic cheap screen (2026-09-20)

**Overall: 0b PASS**

Governed by `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`. Every parameter here is a copy of a pinned value in that document. Per §1(iv) EVERY attempted variant's table appears below, including INSUFFICIENT-DATA ones. Per §2.0 the bar is read on the WINDOW-POOLED cell only; the per-hour tables are diagnosis and are structurally barred from selecting a winner.

## Corpus census (measured, before any verdict)

- venue station-days on the depth tape (4-station pool): **81**
- depth files read: 2768; L0 rows streamed: 9642176
- station-days with NWS CLI settlement truth: **73**
- station-days with an NBS forecast: **81**
- station-days EXCLUDED as an incomplete join (no forecast and/or no settlement truth, so no decision exists to score): **8**
- DENOMINATOR NOTE: `n` below counts station-days with a COMPLETE join, take or no-take. §2.3 reads as though `n` were the with-a-would-take subset; §3's `> 50% of trials have post-fee margin > 0` is vacuous under that reading (every take has margin > 0 by the `min_edge > 0` rule), so the complete-join denominator is used and the take-only median is reported beside it. Flagged to the strategy lead as a registration ambiguity.

- FROZEN 0b error model fitted on 5808 TRAIN station-days (2021-01-01..2024-12-31); sigma is NOT re-fitted here (§2.2 amendment A4).
- FORECAST ARCHIVE GAP for KLAX: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21); the covered remainder is measured below.
- FORECAST ARCHIVE GAP for KMDW: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21); the covered remainder is measured below.
- FORECAST ARCHIVE GAP for KMIA: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21); the covered remainder is measured below.
- FORECAST ARCHIVE GAP for KSFO: 1 runtime day(s) covered by no entry (2026-09-21..2026-09-21); the covered remainder is measured below.

## All twelve variant tables (§1(iv))

| variant | n | takes | % positive margin | median margin | no_bid_side rate | Holm p | Holm threshold | verdict |
|---|---|---|---|---|---|---|---|---|
| `A1-B1-C1` | 73 | 68 | 93.2% | 0.0612 | -- | 0.00000 | 0.00556 | **CLEARS** |
| `A1-B1-C2` | 73 | 35 | 47.9% | 0.0014 | -- | 0.68001 | 0.01667 | **FAILS** |
| `A1-B2-C1` | 73 | 69 | 94.5% | 0.0548 | 0.055 | 0.00000 | 0.00500 | **CLEARS** |
| `A1-B2-C2` | 73 | 67 | 91.8% | 0.0441 | 0.055 | 0.00000 | 0.00625 | **CLEARS** |
| `A2-B1-C1` | 73 | 70 | 95.9% | 0.0628 | -- | 0.00000 | 0.00417 | **CLEARS** |
| `A2-B1-C2` | 73 | 35 | 47.9% | 0.0029 | -- | 0.68001 | 0.02500 | **FAILS** |
| `A2-B2-C1` | 73 | 70 | 95.9% | 0.0725 | 0.041 | 0.00000 | 0.00455 | **CLEARS** |
| `A2-B2-C2` | 73 | 65 | 89.0% | 0.0368 | 0.041 | 0.00000 | 0.01250 | **CLEARS** |
| `A3-B1-C1` | 73 | 66 | 90.4% | 0.0748 | -- | 0.00000 | 0.00714 | **CLEARS** |
| `A3-B1-C2` | 73 | 28 | 38.4% | -0.0048 | -- | 0.98279 | 0.05000 | **FAILS** |
| `A3-B2-C1` | 73 | 66 | 90.4% | 0.0689 | 0.096 | 0.00000 | 0.00833 | **CLEARS** |
| `A3-B2-C2` | 73 | 66 | 90.4% | 0.0567 | 0.096 | 0.00000 | 0.01000 | **CLEARS** |

### Why each cell landed where it did

- `A1-B1-C1`: all §3 conditions met
- `A1-B1-C2`: positive-margin rate 0.479 is not > 0.5; median post-fee margin 0.001419388299142496 is not >= 0.03
- `A1-B2-C1`: all §3 conditions met
- `A1-B2-C2`: all §3 conditions met
- `A2-B1-C1`: all §3 conditions met
- `A2-B1-C2`: positive-margin rate 0.479 is not > 0.5; median post-fee margin 0.002945884123661849 is not >= 0.03
- `A2-B2-C1`: all §3 conditions met
- `A2-B2-C2`: all §3 conditions met
- `A3-B1-C1`: all §3 conditions met
- `A3-B1-C2`: positive-margin rate 0.384 is not > 0.5; median post-fee margin -0.004784628647621053 is not >= 0.03
- `A3-B2-C1`: all §3 conditions met
- `A3-B2-C2`: all §3 conditions met

### Bootstrap intervals on the median post-fee margin

Date is the single PRIMARY and DECISIONAL cluster (§2.2). The station-clustered interval is sensitivity only and is explicitly non-decisional.

| variant | 95% CI (date, DECISIONAL) | 95% CI (station, sensitivity only) |
|---|---|---|
| `A1-B1-C1` | [0.0410, 0.0828] | [0.0483, 0.0764] |
| `A1-B1-C2` | [-0.0176, 0.0107] | [-0.0414, 0.0186] |
| `A1-B2-C1` | [0.0364, 0.0788] | [0.0305, 0.0812] |
| `A1-B2-C2` | [0.0301, 0.0702] | [0.0301, 0.0803] |
| `A2-B1-C1` | [0.0485, 0.0994] | [0.0463, 0.0842] |
| `A2-B1-C2` | [-0.0293, 0.0157] | [-0.0383, 0.0142] |
| `A2-B2-C1` | [0.0412, 0.1017] | [0.0393, 0.0818] |
| `A2-B2-C2` | [0.0317, 0.0573] | [0.0343, 0.0546] |
| `A3-B1-C1` | [0.0504, 0.1033] | [0.0498, 0.1038] |
| `A3-B1-C2` | [-0.0273, 0.0065] | [-0.0478, 0.0029] |
| `A3-B2-C1` | [0.0388, 0.1036] | [0.0368, 0.1210] |
| `A3-B2-C2` | [0.0305, 0.0848] | [0.0301, 0.0976] |

### Per-hour tables -- DIAGNOSIS ONLY, never a selection surface (§2.0)

| variant | hour LST | n | takes |
|---|---|---|---|
| `A1-B1-C1` | 9 | 55 | 55 |
| `A1-B1-C1` | 10 | 12 | 12 |
| `A1-B1-C1` | 11 | 2 | 1 |
| `A1-B1-C2` | 9 | 43 | 25 |
| `A1-B1-C2` | 10 | 15 | 6 |
| `A1-B1-C2` | 11 | 6 | 4 |
| `A1-B2-C1` | 9 | 57 | 57 |
| `A1-B2-C1` | 10 | 11 | 11 |
| `A1-B2-C1` | 11 | 1 | 1 |
| `A1-B2-C2` | 9 | 56 | 55 |
| `A1-B2-C2` | 10 | 12 | 12 |
| `A1-B2-C2` | 11 | 0 | 0 |
| `A2-B1-C1` | 12 | 63 | 63 |
| `A2-B1-C1` | 13 | 0 | 0 |
| `A2-B1-C1` | 14 | 1 | 1 |
| `A2-B1-C1` | 15 | 0 | 0 |
| `A2-B1-C1` | 16 | 6 | 6 |
| `A2-B1-C2` | 12 | 41 | 26 |
| `A2-B1-C2` | 13 | 3 | 1 |
| `A2-B1-C2` | 14 | 6 | 1 |
| `A2-B1-C2` | 15 | 3 | 1 |
| `A2-B1-C2` | 16 | 11 | 6 |
| `A2-B2-C1` | 12 | 63 | 63 |
| `A2-B2-C1` | 13 | 0 | 0 |
| `A2-B2-C1` | 14 | 1 | 1 |
| `A2-B2-C1` | 15 | 0 | 0 |
| `A2-B2-C1` | 16 | 6 | 6 |
| `A2-B2-C2` | 12 | 56 | 56 |
| `A2-B2-C2` | 13 | 1 | 1 |
| `A2-B2-C2` | 14 | 3 | 2 |
| `A2-B2-C2` | 15 | 0 | 0 |
| `A2-B2-C2` | 16 | 8 | 6 |
| `A3-B1-C1` | 10 | 66 | 66 |
| `A3-B1-C2` | 10 | 56 | 28 |
| `A3-B2-C1` | 10 | 66 | 66 |
| `A3-B2-C2` | 10 | 66 | 66 |

## Multiplicity (§1(ii))

Holm-Bonferroni across the ENTIRE enumerated set, `K_variants = 12`, family-wise `alpha = 0.05` one-sided, applied to the SELECTION decision. Cells below the n floor carry `p = 1.0` rather than being dropped, so the family stays at 12 and thin cells cannot inflate power.

Rejections at FWER 0.05: ['A1-B1-C1', 'A1-B2-C1', 'A1-B2-C2', 'A2-B1-C1', 'A2-B2-C1', 'A2-B2-C2', 'A3-B1-C1', 'A3-B2-C1', 'A3-B2-C2']

## §4 disposition

**0b PASS.** Under §4, INSUFFICIENT-DATA is an instruction to extend the corpus or the shadow period. It is never a PASS and never a KILL, and this run exits 0.
