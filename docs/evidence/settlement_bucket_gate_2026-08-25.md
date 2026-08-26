# Settlement Bucket Gate Evidence

Generated at: 2026-08-25T02:19:36+00:00
Phase 2 bucket-alignment gate: **FAIL**
Pre-registration: `docs/evidence/settlement_bucket_gate_prereg_2026-08-25.md`
Command: `/home/jon/breezy/.venv/bin/python scripts/analysis/settlement_bucket_gate.py`
Catalog base: `/home/jon/.local/share/breezy/catalog`
Cache dir: `/tmp/breezy-settlement-alignment-cache`

## Registered Gate

- Historical window: 2021-01-01 through 2025-12-31 (1826 days)
- Bucket agreement: symmetric same-bucket comparison of final CLI `tmax_f` and METAR rounded daily maximum.
- Reconstructed lattice: two-degree buckets, phase offsets 0.0F through 1.9F in 0.1F steps.
- Pass threshold: Wilson 95% lower bound strictly greater than 0.9900.
- Minimum sample: 1000 eligible city-days per city and 5000 eligible city-days total at every phase.
- Phase 2 passes only if every city and the total pass at every preregistered phase.

## Methodological Limitation

The captured venue markets are from 2026 only; no 2021-2025 historical venue bucket ladders are present in the captured data. This report therefore reconstructs an infinite two-degree ladder and treats the preregistered phase sweep as the evidence.

## Venue Bucket Grammar

Parsed captured temperature market slugs: 680
Strike forms: between: 455, gte: 112, lt: 113
Interior slug upper-minus-lower spans: 1: 455
Interior displayed integer bucket widths: 2: 455
Complete captured event ladders: 112
Observed lower interior anchors: 54: 1, 56: 1, 57: 2, 59: 1, 60: 2, 61: 2, 62: 1, 63: 4, 65: 1, 66: 3, 67: 1, 68: 3, 69: 1, 70: 2, 71: 1, 72: 5, 73: 1, 74: 1, 75: 4, 76: 5, 77: 5, 78: 6, 79: 6, 80: 7, 81: 10, 82: 5, 83: 5, 84: 2, 85: 2, 87: 4, 88: 4, 89: 6, 90: 3, 92: 1, 97: 1, 98: 2, 99: 1
Observed anchor parity modulo 2F: 0: 54, 1: 58

Interpretation used for this gate:

- Lower tail `ltNf`: integer CLI values below `N`.
- Interior `gteNltN+1f`: displayed as `N to N+1`, treated as integer values `N` and `N+1`.
- Upper tail `gteNf`: integer CLI values greater than or equal to `N`.
- Captured complete ladders have two-degree interior buckets and two-degree spacing.
- Captured lower anchors vary, including both modulo-2 parities, so the ladder appears forecast-anchored rather than a fixed absolute integer lattice.

First parsed sample slugs:

- `tc-temp-laxhigh-2026-04-22-gte64lt65f`
- `tc-temp-laxhigh-2026-04-22-gte66lt67f`
- `tc-temp-laxhigh-2026-04-22-gte68lt69f`
- `tc-temp-laxhigh-2026-08-24-gte80lt81f`
- `tc-temp-laxhigh-2026-08-24-gte82lt83f`
- `tc-temp-laxhigh-2026-08-24-gte84lt85f`
- `tc-temp-laxhigh-2026-08-24-gte86lt87f`
- `tc-temp-laxhigh-2026-08-24-gte88f`
- `tc-temp-laxhigh-2026-08-24-lt80f`
- `tc-temp-laxhigh-2026-08-25-gte81lt82f`

## Archive Validation Bridge

Status: **passed**
Checked overlapping final records: 36
Mismatches: 0

- checked 36 overlapping final Breezy catalog records
- NYC: expected_cli_location=NYC climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- SFO: expected_cli_location=SFO climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- MIA: expected_cli_location=MIA climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- MDW: expected_cli_location=MDW climate_records=16 raw_products=16 final=8 preliminary=8 wrong_station=0 corrected_finals=1 date_range=2026-08-16..2026-08-24
- LAX: expected_cli_location=LAX climate_records=20 raw_products=20 final=12 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24

## Eligible City-Days

Eligible city-days before phase expansion: 9072

| City | Eligible city-days |
|---|---:|
| LAX | 1820 |
| MDW | 1826 |
| MIA | 1813 |
| NYC | 1814 |
| SFO | 1799 |

## Per-City Verdicts

Worst phase is the preregistered phase with the lowest Wilson lower bound for that city.

| City | Worst phase F | Cases | Agreements | Misses | Agreement rate | Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| LAX | 0.1 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| MDW | 0.1 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MIA | 0.0 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| NYC | 0.1 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| SFO | 0.1 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |

## Lattice Offset Sensitivity

| Phase offset F | Cases | Agreements | Misses | Agreement rate | Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | Verdict |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0.0 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 0.1 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.2 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.3 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.4 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.5 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.6 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.7 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.8 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 0.9 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 1.0 | 9072 | 6932 | 2140 | 0.764109 | 0.755262 | 1520 | 620 | FAIL |
| 1.1 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.2 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.3 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.4 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.5 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.6 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.7 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.8 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |
| 1.9 | 9072 | 6988 | 2084 | 0.770282 | 0.761513 | 1372 | 712 | FAIL |

## Per-City By Phase

| City | Phase offset F | Cases | Agreements | Misses | Agreement rate | Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| LAX | 0.0 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 0.1 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.2 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.3 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.4 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.5 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.6 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.7 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.8 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 0.9 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 1.0 | 1820 | 1387 | 433 | 0.762088 | 0.741986 | 263 | 170 | FAIL |
| LAX | 1.1 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.2 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.3 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.4 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.5 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.6 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.7 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.8 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| LAX | 1.9 | 1820 | 1401 | 419 | 0.769780 | 0.749884 | 247 | 172 | FAIL |
| MDW | 0.0 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 0.1 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.2 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.3 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.4 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.5 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.6 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.7 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.8 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 0.9 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 1.0 | 1826 | 1491 | 335 | 0.816539 | 0.798128 | 162 | 173 | FAIL |
| MDW | 1.1 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.2 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.3 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.4 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.5 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.6 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.7 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.8 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MDW | 1.9 | 1826 | 1498 | 328 | 0.820372 | 0.802098 | 131 | 197 | FAIL |
| MIA | 0.0 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 0.1 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.2 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.3 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.4 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.5 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.6 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.7 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.8 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 0.9 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 1.0 | 1813 | 1446 | 367 | 0.797573 | 0.778457 | 269 | 98 | FAIL |
| MIA | 1.1 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.2 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.3 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.4 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.5 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.6 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.7 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.8 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| MIA | 1.9 | 1813 | 1425 | 388 | 0.785990 | 0.766517 | 214 | 174 | FAIL |
| NYC | 0.0 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 0.1 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.2 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.3 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.4 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.5 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.6 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.7 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.8 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 0.9 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 1.0 | 1814 | 1212 | 602 | 0.668137 | 0.646132 | 600 | 2 | FAIL |
| NYC | 1.1 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.2 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.3 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.4 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.5 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.6 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.7 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.8 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| NYC | 1.9 | 1814 | 1229 | 585 | 0.677508 | 0.655642 | 582 | 3 | FAIL |
| SFO | 0.0 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 0.1 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.2 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.3 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.4 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.5 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.6 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.7 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.8 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 0.9 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 1.0 | 1799 | 1396 | 403 | 0.775987 | 0.756144 | 226 | 177 | FAIL |
| SFO | 1.1 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.2 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.3 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.4 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.5 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.6 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.7 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.8 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |
| SFO | 1.9 | 1799 | 1435 | 364 | 0.797665 | 0.778476 | 198 | 166 | FAIL |

## Agreement By CLI Distance To Bucket Edge

| CLI distance to nearest bucket edge F | Cases | Agreements | Misses | Agreement rate | Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | 9072 | 6434 | 2638 | 0.709215 | 0.699783 | 2630 | 8 |
| 0.1 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.2 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.3 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.4 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.5 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.6 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.7 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.8 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 0.9 | 18144 | 13920 | 4224 | 0.767196 | 0.760990 | 2892 | 1332 |
| 1.0 | 9072 | 7486 | 1586 | 0.825176 | 0.817223 | 262 | 1324 |

## Drop Counts

- LAX:archive_parse_error: 1
- LAX:missing_cli_final: 6
- LAX:missing_metar_t_group_row: 10053
- MDW:archive_parse_error: 1
- MDW:missing_metar_t_group_row: 17008
- MIA:archive_parse_error: 1
- MIA:cli_sentinel: 6
- MIA:missing_cli_final: 7
- MIA:missing_metar_t_group_row: 6410
- NYC:archive_parse_error: 2
- NYC:missing_cli_final: 4
- NYC:missing_metar_t_group: 8
- NYC:missing_metar_t_group_row: 2307
- SFO:archive_parse_error: 1
- SFO:cli_sentinel: 10
- SFO:missing_cli_final: 17
- SFO:missing_metar_t_group_row: 6134

## Parse Issues

- NYC CLINYC_202403011441.txt: CliContentError: no recognizable '...THE <SITE> CLIMATE SUMMARY FOR <DATE>...' headline found
- NYC CLINYC_202403011441.txt: CliContentError: no recognizable '...THE <SITE> CLIMATE SUMMARY FOR <DATE>...' headline found
- SFO CLISFO_202504140836.txt: CliStructuralError: product has no AWIPS PIL on line 4 of the transmission header
- MIA CLIMIA_202504140821.txt: CliStructuralError: product has no AWIPS PIL on line 4 of the transmission header
- MDW CLIMDW_202211122236.txt: CliContentError: unrecognized temperature token: '37E'
- LAX CLILAX_202504140842.txt: CliStructuralError: product has no AWIPS PIL on line 4 of the transmission header
