# LOT (KMDW) PFM day-1 MAX vs CLI high, 2021–2024

Read-only. No writes under `~/.local/share/breezy` or the repo. PFM bytes were sha256-checked against the manifest before parse (0 mismatches).

## Stores

- PFM: `UsSourceRevisionStore` / `ArchiveCache` at `~/.local/share/breezy/us_source_archive/us-pfm-afos`, station `KMDW`, model `LOT`, product `pfm-r0`. Values from `parse_pfm_product` (`_MAX_COLUMNS = {(0, None), (23, 18)}`). Column hour is the UTC hour of the cell the parser accepted as MAX; the hour walk matched `max_by_day` on every paired product.
- CLI: settlement-truth CSV `~/.local/share/breezy/derived/settlement-truth/settlement_truth.csv`, station `MDW` (Chicago Midway = KMDW), `status=FINAL`, blank `tmax_flag`. The F2 AFOS cache (`derived/fq-truth`) starts 2026-01-01 and has no 2021–2024 rows, so it was not the truth source.

## Selection rule

For climate day D, take the `pfm-r0` issuance whose America/Chicago local date is D−1 and whose instant is closest to **06:00 America/Chicago on D−1** (tie: earlier instant, then cache key). Score only that product's parsed MAX for D. Error = PFM MAX − CLI high.

1323/1326 chosen issuances are 06:15 local (5 are 06:16; 3 fall back to 05/07/18 when 06:15 was absent). Re-ingest flag: issuance UTC date in **[2021-03-14, 2022-08-11]**. DST: America/Chicago noon on the climate day is on daylight time. Same-season control: not re-ingested, CDT, month-day in [03-14, 08-11], MAX column UTC 00.

Paired days: **1326** (2021-01-01 .. 2024-08-18). 2024-08-19 .. 2024-12-31 have no KMDW PFM in the store. Parse failures: 0.

## Error distribution

| cohort | n | mean | MAE | p5 | p50 | p95 | \|err\|>10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 1326 | -1.91 | 2.95 | -7 | -2 | 3 | 2.0% |
| DST | 876 | -1.68 | 2.77 | -6 | -2 | 3 | 0.7% |
| standard | 450 | -2.36 | 3.30 | -9 | -2 | 3 | 4.4% |
| 2021 | 365 | -1.49 | 2.72 | -7 | -1 | 4 | 1.6% |
| 2021 DST | 238 | -1.02 | 2.50 | -6 | -1 | 4.1 | 0.4% |
| 2021 standard | 127 | -2.36 | 3.12 | -8 | -2 | 2 | 3.9% |
| 2022 | 365 | -2.73 | 3.51 | -9.8 | -2 | 3 | 3.8% |
| 2022 DST | 238 | -2.59 | 3.30 | -7.1 | -3 | 3 | 0.8% |
| 2022 standard | 127 | -2.98 | 3.91 | -13 | -2 | 3 | 9.4% |
| 2023 | 365 | -1.48 | 2.58 | -6 | -1 | 3 | 0.8% |
| 2023 DST | 238 | -1.32 | 2.45 | -5 | -1 | 3 | 0.4% |
| 2023 standard | 127 | -1.77 | 2.83 | -7 | -2 | 2 | 1.6% |
| 2024 (through 08-18) | 231 | -1.98 | 3.01 | -7 | -2 | 3.5 | 1.3% |
| 2024 DST | 162 | -1.85 | 2.85 | -7 | -2 | 3 | 1.2% |
| 2024 standard | 69 | -2.29 | 3.39 | -8.6 | -2 | 4 | 1.4% |
| **reingest CDT, col 23Z** | **389** | **-1.64** | **2.89** | **-7** | **-2** | **4** | **0.8%** |
| reingest CDT, other column | 1 | -2.00 | 2.00 | -2 | -2 | -2 | 0% |
| reingest CST, col 00Z | 125 | -3.75 | 4.34 | -13 | -3 | 2 | 10.4% |
| **old-parse CDT, col 00Z** | **486** | **-1.71** | **2.67** | **-6** | **-2** | **3** | **0.6%** |
| **old-parse CDT, same season, col 00Z** | **303** | **-1.73** | **2.83** | **-6** | **-2** | **3** | **1.0%** |
| old-parse CST, col 00Z | 324 | -1.83 | 2.91 | -7 | -1 | 3 | 2.2% |

Column layout matches the parser contract. Re-ingested CDT maxima are UTC 23 / local 18 (389/390; the one UTC 00 is climate day 2022-03-13, whose D−1 issuance on 2022-03-12 was still CST). After the re-ingest window, CDT maxima are UTC 00 / local 19. The single standard-time 23Z row is 2021-11-07, issued 2021-11-06 while CDT was still in effect (error −1°F).

23Z vs same-season 00Z: mean differs by **0.08°F**, MAE by **0.06°F**, \|err\|>10 by **0.2 points**. No fixed offset. The 23Z cohort has 3 days with \|err\|>10 (−13, +11, −11), not a pile at one delta.

Re-ingested CST (2021-11 .. 2022-03, still the old UTC 00 / local 18 column) is colder than other winters (mean −3.75 vs −1.83, 13 days \|err\|>10, all negative, −11 to −19). That tail is the same shape as old-parse winter busts, and the worst day in the whole sample is outside the re-ingest (2024-02-28, −25°F, UTC 00). It is not a 23Z-column or wrong-date signature.

## 10 worst examples

| climate day | issuance id (cache key) | issued UTC | col | PFM | CLI | err | cohort |
|---|---|---|---|---:|---:|---:|---|
| 2024-02-28 | `1c7af8d5d87addb826a69f18221431a762d2760c036c8d6b090352feb756a6c1` | 2024-02-27T12:15Z | 00Z/18L | 28 | 53 | -25 | old CST |
| 2022-12-03 | `fef6d45beb3f3b695b3b0350cddb7ebe9aab881ec7828389bd531b9e8ebb0071` | 2022-12-02T12:15Z | 00Z/18L | 31 | 52 | -21 | old CST |
| 2024-04-02 | `c18712235e4a2532c9cc783e79ece7ceb72d51093541273fd242c6e412f2365c` | 2024-04-01T11:15Z | 00Z/19L | 42 | 62 | -20 | old CDT |
| 2021-12-16 | `4746d16d6ee801c69c40f0555b885e078a17451c724cbf4420e67d94aa7ef57e` | 2021-12-15T12:15Z | 00Z/18L | 48 | 67 | -19 | reingest CST |
| 2021-03-03 | `e1d606b237511484bd6c1a445c0187b18cc6da7a688c17ed1d1dde346b8a9699` | 2021-03-02T12:15Z | 00Z/18L | 42 | 60 | -18 | old CST |
| 2021-12-11 | `683d7e308f6d71a2a96d379d43da5e36b4b50fb9f84ffe8da8f9354603e1a4f5` | 2021-12-10T12:15Z | 00Z/18L | 42 | 59 | -17 | reingest CST |
| 2022-01-19 | `3a391593022af16ca48143b1eb1ceeb703b09243d457c56a31046f07b3504f1b` | 2022-01-18T12:15Z | 00Z/18L | 26 | 43 | -17 | reingest CST |
| 2022-12-30 | `a824cf645c616d87470126bdf39b220d66fdd8c28db8ffa45e1065810345db9c` | 2022-12-29T12:15Z | 00Z/18L | 40 | 57 | -17 | old CST |
| 2022-01-05 | `d183a378dfe7f97858725cca8b599c49d5c8bf7015b399956782f9e3b1b03983` | 2022-01-04T12:15Z | 00Z/18L | 19 | 35 | -16 | reingest CST |
| 2021-12-10 | `3bf2dfb3b9af7ad43940bd7500a97a8ab31610a6d4bdf45e10d4fd046fab3b26` | 2021-12-09T12:15Z | 00Z/18L | 47 | 61 | -14 | reingest CST |

None of these are 23Z. The three 23Z re-ingest days with |err|>10 are 2022-03-17 (−13, 23Z/18L, PFM 61, CLI 74, `b5ca9624a633c080d727452d827a03e80767874247d179d55f6e8ecba1af0ec9`), 2021-03-26 (+11, 23Z/18L, PFM 53, CLI 42, `a6f5ee7bbc0ae5b068bdd3421eb8644386e0dd35298041286ac7703fa59b23e0`), and 2022-05-11 (−11, 23Z/18L, PFM 80, CLI 91, `df34296b0c771bfdb3f2623f73dbb8cdb88f6a96ddfb3cf587d21e73be251401`). Full pairs: `pairs.csv`. Machine summary: `summary.json`.

## Verdict: **OK**

The re-ingested CDT 23Z-column maxima agree with same-season CDT products parsed on the UTC 00 column (mean −1.64 vs −1.73, MAE 2.89 vs 2.83, \|err\|>10 0.8% vs 1.0%). No systematic offset and no 10°F cluster on the 23Z path. Those years can carry weight in the F13 blend on this check. The shared ~2°F cold bias is forecast error, present on both layouts.
