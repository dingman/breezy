# Receipt Lag Probe

Generated: 2026-08-29T21:22:25+00:00

Catalog base: `/home/jon/.local/share/breezy/catalog`

## Scope

This is a read-only measurement of the live Breezy NWS catalog. The probe opened existing station roots directly with `ParquetDataCatalog(path=...)` and did not call `open_station_catalog()`, because that helper creates missing catalog directories.

The sample is small and operationally local: it covers only the records currently present in this catalog. High percentiles inside station/class splits are order statistics from a handful of rows and should be treated as a current sanity measurement, not a settled long-run service-level estimate.

## Issuance Derivation

For each `NwsClimateDay`, the probe joined to `NwsRawProduct` by `raw_sha256`, verified the raw-product digest, and parsed issuance from the raw product text. The primary parser reads the WMO heading day/hour/minute and anchors month/year from the product receipt timestamp. That matches the plan's WMO issuance-clock language and avoids treating a correction product's stale body issue line as the correction issuance. If the WMO heading is unavailable, the fallback uses the same local-time issuance-line pattern as `scripts/analysis/settlement_alignment_study.py`. The climate-day `issuance_time_ns` field is checked against the derived instant but is not the primary derivation source.

## Population Split

The catalog does not carry a row-level `gap_recovery` vs `routine_poll` fetch path marker. `source_channel` is the fetched product URL, so it identifies the NWS product but not the caller path that fetched it.

The split therefore uses the documented cold-start recovery window from `docs/evidence/ingestion/COLLECTION_RESTART_2026-08-24.md`: first recovery poll began at 2026-08-24T19:50:55Z and the final first-poll persistence line was 2026-08-24T19:55:08Z. Rows with `retrieved_at_ns` in [2026-08-24T19:50:55Z, 2026-08-24T19:55:09Z) are classified as `recovery_ingestion`; all later rows are classified as `steady_state`.

| Population | n | first retrieved UTC | last retrieved UTC | min lag | max lag |
|---|---:|---|---|---:|---:|
| steady_state (plan-relevant) | 56 | 2026-08-24T20:27:55.623075+00:00 | 2026-08-29T20:55:55.749380+00:00 | 115.7 | 1195.6 |
| recovery_ingestion | 76 | 2026-08-24T19:50:55.922496+00:00 | 2026-08-24T19:55:08.305501+00:00 | 40443.9 | 603775.8 |

## Superseded Mixed Figure

An earlier version of this report pooled steady-state and recovery-ingestion rows and reported p95 567236.6 seconds. That figure is superseded because it mixes two populations: routine product polling and post-restart recovery of products issued days earlier.

## Plan-Relevant Headline

- Records measured: 132
- Records where issuance was not derivable: 0
- Negative lags: 0
- Issuance source counts: {'wmo_heading': 132}
- Steady-state p95: 895.7 seconds (14.93 minutes)
- Steady-state observed max: 1195.6 seconds
- Recovery-ingestion p95: 598676.4 seconds

The steady-state sample has n=56, above the n=20 stop line but still small. The nearest-rank p95 is rank 54/56 = 895.7 seconds (14.93 minutes); the observed max is 1195.6 seconds (19.93 minutes).

## Lag Distribution By Population

Percentiles use nearest-rank observed values in seconds.

| Group | n | min | p50 | p90 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| recovery_ingestion | 76 | 40443.9 | 328559.6 | 566037.1 | 598676.4 | 603775.8 |
| steady_state (plan-relevant) | 56 | 115.7 | 355.8 | 655.6 | 895.7 | 1195.6 |

## Lag Distribution By Population And Issuance Class

| Group | n | min | p50 | p90 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| recovery_ingestion class=final | 41 | 40443.9 | 307261.0 | 559856.3 | 566037.1 | 603775.8 |
| recovery_ingestion class=preliminary | 35 | 65947.1 | 342359.8 | 588415.7 | 601615.9 | 602935.7 |
| steady_state class=final | 27 | 175.6 | 355.8 | 595.7 | 895.7 | 1195.6 |
| steady_state class=preliminary | 29 | 115.7 | 415.6 | 655.7 | 655.9 | 895.7 |

## Lag Distribution By Population And Station

| Group | n | min | p50 | p90 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| recovery_ingestion station=LAX | 19 | 40508.3 | 386101.6 | 560036.4 | 584455.8 | 584455.8 |
| recovery_ingestion station=MDW | 15 | 47645.0 | 339660.4 | 598676.4 | 603775.8 | 603775.8 |
| recovery_ingestion station=MIA | 14 | 41284.0 | 300540.2 | 559856.3 | 602935.7 | 602935.7 |
| recovery_ingestion station=NYC | 14 | 47944.1 | 307440.5 | 567236.6 | 601615.9 | 601615.9 |
| recovery_ingestion station=SFO | 14 | 40443.9 | 300420.2 | 559376.4 | 588415.7 | 588415.7 |
| steady_state station=LAX | 13 | 115.7 | 415.7 | 895.7 | 1195.6 | 1195.6 |
| steady_state station=MDW | 10 | 235.7 | 415.6 | 535.7 | 535.8 | 535.8 |
| steady_state station=MIA | 11 | 175.6 | 355.6 | 655.7 | 655.9 | 655.9 |
| steady_state station=NYC | 12 | 175.7 | 295.8 | 535.7 | 595.7 | 595.7 |
| steady_state station=SFO | 10 | 295.6 | 415.6 | 595.7 | 655.6 | 655.6 |

## Split Evidence

Lag histogram, in fixed human-readable buckets, with the empty middle visible:

| Lag bucket | steady_state | recovery_ingestion |
|---|---:|---:|
| <=5m | 18 | 0 |
| 5-10m | 32 | 0 |
| 10-20m | 6 | 0 |
| 20m-1h | 0 | 0 |
| 1-12h | 0 | 4 |
| 12h-2d | 0 | 18 |
| 2-4d | 0 | 19 |
| >4d | 0 | 35 |

Boundary rows around the population separation:

| Boundary row | city | climate day | class | retrieved UTC | lag seconds |
|---|---|---|---|---|---:|
| largest steady-state lag | LAX | 2026-08-25 | final | 2026-08-26T08:59:55.614294+00:00 | 1195.6 |
| smallest recovery-ingestion lag | SFO | 2026-08-23 | final | 2026-08-24T19:52:03.878533+00:00 | 40443.9 |
| empty lag interval between them | n/a | n/a | n/a | n/a | 39248.3 |

## Station Read Summary

| City | climate records | expected station records | raw products | measured | non-derivable | wrong-station |
|---|---:|---:|---:|---:|---:|---:|
| LAX | 32 | 32 | 32 | 32 | 0 | 0 |
| MDW | 25 | 25 | 25 | 25 | 0 | 0 |
| MIA | 25 | 25 | 25 | 25 | 0 | 0 |
| NYC | 26 | 26 | 26 | 26 | 0 | 0 |
| SFO | 24 | 24 | 24 | 24 | 0 | 0 |

## Non-Derivable Records

- none

No records were non-derivable.

## Negative Lags

No negative lags were observed.

## Consistency Check

All measured rows had climate-day `issuance_time_ns` within 60 seconds of the parsed raw-product issuance instant.

## WMO vs Local Issue Line

| City | climate day | class | issued line minus WMO seconds | raw_sha256 |
|---|---|---|---:|---|
| MDW | 2026-08-16 | final | -48060.000 | `92dbf9a7b5529607cc2f305420d5e4fb37469c90163b6ebcac2c038f6c44007f` |

## Read Errors

- none

## Backfill Plan Implication

For the backfill plan, use the steady-state population, not the pooled distribution: current observed steady-state p95 is 895.7 seconds (14.93 minutes), with an observed steady-state max of 1195.6 seconds (19.93 minutes). This is a provisional n=56 estimate, not a long-run SLO.
