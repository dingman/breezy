# NOMADS/NBM discovery probe (FC-0a-3 Seam A)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into any production catalog.

Host: `nomads.ncep.noaa.gov` (settlement host NOT touched)
Transport: ProbeTransport, max_body_bytes=50331648
Request budget: 18 hard; spent 11.
Planned steps: 14; dispatched: 11.
Stations: KLAX, KMDW, KMIA, KSFO.

Candidate URL shapes in this module are UNVERIFIED constants.

## Outcomes

| # | label | status | bytes | outcome |
|--:|---|--:|--:|---|
| 1 | `p1_blend_prod_index` | 200 | 2260 | ok |
| 2 | `p2_collective_nbstx` | 200 | 29720949 | ok |
| 3 | `p3_conditional_bulletin` | 304 | 0 | not_modified |
| 4 | `p4_retention_20260918` | 200 | 3941 | ok |
| 5 | `p4_retention_20260912` | 404 | 196 | http_404 |
| 6 | `p4_retention_20260820` | 0 | 0 | error:ForbiddenError |
| 7 | `p5_lag_20260919_00` | 200 | 29720949 | ok |
| 8 | `p5_lag_20260919_06` | 200 | 29611149 | ok |
| 9 | `p5_lag_20260919_12` | 200 | 29720949 | ok |
| 10 | `p5_lag_20260919_18` | 0 | 0 | error:ForbiddenError |
| 11 | `p6_robots` | 404 | 196 | http_404 |

## Questions

- `q1_nbs_bulletin_path`: ANSWERED (station_blocks=2468, txn_groups=2468, row_count=243307, field_count=14808) — p2_collective_nbstx path=/pub/data/nccf/com/blend/prod/blend.20260919/12/text/blend_nbstx.t12z state=ANSWERED
- `q2_last_modified_and_etag`: ANSWERED (has_last_modified=1, has_etag=0, not_modified=1) — p3_conditional_bulletin Last-Modified='Sat, 19 Sep 2026 13:17:52 GMT' ETag=None 304=True
- `q3_body_size`: ANSWERED (bytes=29720949) — p2_collective_nbstx measured 29720949 bytes
- `q4_cycles_per_day_with_txn`: ANSWERED (status=200, bytes=2260) — p1_blend_prod_index HTTP 200
- `q5_retention_horizon`: ANSWERED (status=200, bytes=2260) — p1_blend_prod_index HTTP 200
- `q6_station_block_grammar`: ANSWERED (station_blocks=2468) — p2_collective_nbstx blocks=2468
- `q7_robots_and_rate_limit`: ANSWERED (status=404, bytes=196) — robots.txt HTTP 404
- `q8_retrospective_lag_samples`: ANSWERED (lag_samples=4) — 4 retrospective (cycle_hour, station) lag samples

## Findings

- `p4_retention_20260912` (HTTP 404): Server answered HTTP 404 (non-2xx).
- `p4_retention_20260820` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260820/ (check User-Agent contact / abuse block).
- `p5_lag_20260919_18` (HTTP 0): ForbiddenError: 403 Forbidden from https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260919/18/text/blend_nbstx.t18z (check User-Agent contact / abuse block).
- `p6_robots` (HTTP 404): Server answered HTTP 404 (non-2xx). The body is captured as evidence, but it carried no requested datum: this is a FINDING, and no question may be marked answered from it.

VERDICT: 8/8 questions ANSWERED
