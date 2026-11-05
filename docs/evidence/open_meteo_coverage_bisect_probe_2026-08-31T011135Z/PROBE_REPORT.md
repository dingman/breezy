# Open-Meteo archive-coverage bisect (P2 Probe C)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into the production forecast
catalog. Backfilling them under a plausible retrieval timestamp would
be backdating and would violate the point-in-time forecast design.

Host: previous-runs-api.open-meteo.com (settlement host NOT touched)
Transport: `breezy.ingest.probe_transport.ProbeTransport`, max_body_bytes=524288
Request budget: 16 hard; spent 16.
Measured variable: `temperature_2m_previous_day1` (hourly), 7-day windows at NYC.

## 1. Coverage matrix (non-null hours / hours returned)

| date | `best_match` | `ecmwf_ifs025` | `gfs_seamless` | `icon_seamless` |
|---|---|---|---|---|
| 2022-01-01 | 168/168 | 0/168 | 168/168 | 0/168 |
| 2024-01-01 | 0/168 | 0/168 | 0/168 | 0/168 |

**Null-ness is a function of: both.**

## 2. Boundary bisect

Reference (best-covered) model: `best_match`

| date | covered |
|---|---|
| 2022-01-01 | yes |
| 2023-01-01 | yes |
| 2023-07-02 | yes |
| 2023-10-01 | yes |
| 2023-11-16 | yes |
| 2023-12-09 | yes |
| 2024-01-01 | no |

Boundary bracketed between 2023-12-09 (covered) and 2024-01-01 (empty) -- 23 days wide, resolution target 31 days.

## 3. Contiguity inside the covered span

| interior date | coverage |
|---|---|
| 2022-06-26 | 168/168 |
| 2022-12-19 | 168/168 |
| 2023-06-13 | 168/168 |

**Coverage inside the span is CONTIGUOUS.**

## Exchanges

| # | label | status | bytes | outcome |
|--:|---|--:|--:|---|
| 1 | `matrix_2022-01-01_best_match` | 200 | 5058 | ok |
| 2 | `matrix_2022-01-01_ecmwf_ifs025` | 200 | 5202 | ok |
| 3 | `matrix_2022-01-01_gfs_seamless` | 200 | 5059 | ok |
| 4 | `matrix_2022-01-01_icon_seamless` | 200 | 5201 | ok |
| 5 | `matrix_2024-01-01_best_match` | 200 | 5082 | ok |
| 6 | `matrix_2024-01-01_ecmwf_ifs025` | 200 | 5201 | ok |
| 7 | `matrix_2024-01-01_gfs_seamless` | 200 | 5083 | ok |
| 8 | `matrix_2024-01-01_icon_seamless` | 200 | 5064 | ok |
| 9 | `bisect_2023-01-01_best_match` | 200 | 4996 | ok |
| 10 | `bisect_2023-07-02_best_match` | 200 | 5206 | ok |
| 11 | `bisect_2023-10-01_best_match` | 200 | 5205 | ok |
| 12 | `bisect_2023-11-16_best_match` | 200 | 5018 | ok |
| 13 | `bisect_2023-12-09_best_match` | 200 | 4934 | ok |
| 14 | `contiguity_2022-06-26_best_match` | 200 | 5206 | ok |
| 15 | `contiguity_2022-12-19_best_match` | 200 | 5122 | ok |
| 16 | `contiguity_2023-06-13_best_match` | 200 | 5206 | ok |

## Findings

None recorded: every dispatched request returned a measurable cell.

## Verdict

2024-01-01 returned an all-null temperature_2m_previous_day1 series for every model tested (best_match, ecmwf_ifs025, gfs_seamless, icon_seamless), while the SAME request shape returned values at 2022-01-01, 2022-06-26, 2022-12-19, 2023-01-01, 2023-06-13, 2023-07-02, 2023-10-01, 2023-11-16, 2023-12-09. The null is the archive's, not the request's.

VERDICT: archive_reaches_2024_01 = REFUTED
