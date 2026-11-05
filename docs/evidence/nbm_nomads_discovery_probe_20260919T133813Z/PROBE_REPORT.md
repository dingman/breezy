# NOMADS/NBM discovery probe (FC-0a-3 Seam A)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into any production catalog.

Host: `nomads.ncep.noaa.gov` (settlement host NOT touched)
Transport: ProbeTransport, max_body_bytes=4194304
Request budget: 18 hard; spent 13.
Planned steps: 17; dispatched: 13.
Stations: KLAX, KMDW, KMIA, KSFO.

Candidate URL shapes in this module are UNVERIFIED constants.

## Outcomes

| # | label | status | bytes | outcome |
|--:|---|--:|--:|---|
| 1 | `p1_blend_prod_index` | 200 | 2260 | ok |
| 2 | `p2_collective_nbsta` | 404 | 196 | http_404 |
| 3 | `p2_per_station_nbsta_suffix` | 0 | 0 | error:ForbiddenError |
| 4 | `p2_per_station_nbsta_prefix` | 404 | 196 | http_404 |
| 5 | `p2_per_station_nbstx` | 0 | 0 | error:ForbiddenError |
| 6 | `p4_retention_20260918` | 200 | 3941 | ok |
| 7 | `p4_retention_20260912` | 404 | 196 | http_404 |
| 8 | `p4_retention_20260820` | 0 | 0 | error:ForbiddenError |
| 9 | `p5_lag_20260919_00` | 200 | 2741 | ok |
| 10 | `p5_lag_20260919_06` | 200 | 2635 | ok |
| 11 | `p5_lag_20260919_12` | 200 | 2741 | ok |
| 12 | `p5_lag_20260919_18` | 0 | 0 | error:ForbiddenError |
| 13 | `p6_robots` | 404 | 196 | http_404 |

## Questions

- `q1_nbs_bulletin_path`: UNANSWERED — not reached in this run
- `q2_last_modified_and_etag`: UNANSWERED — not reached in this run
- `q3_body_size`: ANSWERED (bytes=196) — p2_per_station_nbsta_prefix measured 196 bytes
- `q4_cycles_per_day_with_txn`: ANSWERED (status=200, bytes=2260) — p1_blend_prod_index HTTP 200
- `q5_retention_horizon`: ANSWERED (status=200, bytes=2260) — p1_blend_prod_index HTTP 200
- `q6_station_block_grammar`: UNANSWERED — not reached in this run
- `q7_robots_and_rate_limit`: ANSWERED (status=404, bytes=196) — robots.txt HTTP 404
- `q8_retrospective_lag_samples`: UNANSWERED — not reached in this run

## Findings

- `p2_collective_nbsta` (HTTP 404): Server answered HTTP 404 (non-2xx).
- `p2_per_station_nbsta_suffix` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260919/12/text/blend_nbsta.t12z.KMIA (check User-Agent contact / abuse block).
- `p2_per_station_nbsta_prefix` (HTTP 404): Server answered HTTP 404 (non-2xx).
- `p2_per_station_nbstx` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260919/12/text/blend_nbstx.t12z.KMIA (check User-Agent contact / abuse block).
- `p4_retention_20260912` (HTTP 404): Server answered HTTP 404 (non-2xx).
- `p4_retention_20260820` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260820/ (check User-Agent contact / abuse block).
- `p5_lag_20260919_18` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260919/18/text/ (check User-Agent contact / abuse block).
- `p6_robots` (HTTP 404): Server answered HTTP 404 (non-2xx). The body is captured as evidence, but it carried no requested datum: this is a FINDING, and no question may be marked answered from it.

VERDICT: 4/8 questions ANSWERED
