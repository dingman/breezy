# Settlement-Alignment Failure Diagnosis

Generated at: 2026-08-25T01:25:59+00:00
Command: `python scripts/analysis/settlement_alignment_diagnosis.py --catalog-base /home/jon/.local/share/breezy/catalog --cache-dir /tmp/breezy-settlement-alignment-cache --output docs/evidence/settlement_alignment_diagnosis_2026-08-25.md`
Catalog base: `/home/jon/.local/share/breezy/catalog`
Cache dir: `/tmp/breezy-settlement-alignment-cache`
Historical window: 2021-01-01 through 2025-12-31 (1826 days)
Primary gate: Wilson 95% lower bound > 0.9906

## Data Integrity Checks

- Archive-validation bridge status: **passed**
- Checked overlapping final Breezy catalog records: 36
- Validation mismatches: 0
- Parsed threshold cases: 36288
- Parsed unique city-days: 9072
- Parse issues: 6

- checked 36 overlapping final Breezy catalog records
- NYC: expected_cli_location=NYC climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- SFO: expected_cli_location=SFO climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- MIA: expected_cli_location=MIA climate_records=15 raw_products=15 final=7 preliminary=8 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-24
- MDW: expected_cli_location=MDW climate_records=16 raw_products=16 final=8 preliminary=8 wrong_station=0 corrected_finals=1 date_range=2026-08-16..2026-08-24
- LAX: expected_cli_location=LAX climate_records=19 raw_products=19 final=12 preliminary=7 wrong_station=0 corrected_finals=0 date_range=2026-08-17..2026-08-23

## 1. Signed Error Structure

Signed error is `rounded_metar_max_f - cli_tmax_f`, one row per unique city-day. The threshold-case count is exactly four times the city-day count; repeating by threshold does not change the mean, median, or stddev.

| City | City-days | Mean signed F | Median | Stddev | Nonzero days | METAR < CLI | METAR > CLI |
|---|---:|---:|---:|---:|---:|---:|---:|
| LAX | 1820 | -0.102198 | 0.0 | 0.759913 | 802 | 460 (0.573566) | 342 (0.426434) |
| MDW | 1826 | 0.052574 | 0.0 | 0.725439 | 651 | 284 (0.436252) | 367 (0.563748) |
| MIA | 1813 | -0.118036 | 0.0 | 0.662085 | 733 | 462 (0.630286) | 271 (0.369714) |
| NYC | 1814 | -0.668688 | -1.0 | 0.790615 | 1026 | 1023 (0.997076) | 3 (0.002924) |
| SFO | 1799 | -0.051695 | 0.0 | 0.750094 | 742 | 401 (0.540431) | 341 (0.459569) |

Full signed-difference distributions, in whole Fahrenheit degrees:

- LAX: -7: 1, -5: 1, -4: 1, -3: 8, -2: 39, -1: 410, 0: 1018, 1: 342
- MDW: -4: 1, -3: 1, -2: 7, -1: 275, 0: 1175, 1: 364, 7: 1, 9: 1, 12: 1
- MIA: -5: 1, -2: 20, -1: 441, 0: 1080, 1: 270, 2: 1
- NYC: -15: 1, -5: 1, -4: 2, -3: 22, -2: 133, -1: 864, 0: 788, 1: 1, 2: 1, 8: 1
- SFO: -7: 1, -5: 3, -4: 1, -3: 3, -2: 15, -1: 378, 0: 1057, 1: 339, 3: 1, 8: 1

Conclusion: The failed airport sites do not show a well-supported scalar bias correction: their means are close to zero, medians are 0 F, and nonzero signs are mixed. The gate failures come from positive METAR-over-CLI days near the boundary, while negative METAR-under-CLI days are conservative for these threshold cases.

## 2. NYC Versus Airport ASOS Cities

| City | ICAO | CLI location | IEM ASOS id | Evaluated days | Window coverage | Raw METAR rows | T-group rows | UTC days with T-group | Mean T-group rows/UTC day |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| LAX | KLAX | LAX | LAX | 1820 | 0.996714 | 569404 | 559351 | 1828 | 305.99 |
| MDW | KMDW | MDW | MDW | 1826 | 1.000000 | 571149 | 554141 | 1828 | 303.14 |
| MIA | KMIA | MIA | MIA | 1813 | 0.992881 | 568296 | 561886 | 1828 | 307.38 |
| NYC | KNYC | NYC | NYC | 1814 | 0.993428 | 55809 | 53502 | 1821 | 29.38 |
| SFO | KSFO | SFO | SFO | 1799 | 0.985214 | 567599 | 561465 | 1828 | 307.15 |

Study drop counts:

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

NYC does not pass because it retained far more days: its evaluated-day coverage is comparable to the airport sites. The validation bridge also found no wrong-station catalog records for any city and no checked catalog/archive mismatches, so the local data does not show a KNYC-specific CLI join artifact. What the local data does show is a strong station-class correlation in sign: KNYC's nonzero signed errors are almost entirely METAR < CLI, while the airport ASOS cities have hundreds of METAR > CLI days that can create false-positive threshold hits near the boundary.

This local evidence cannot distinguish a genuine instrumentation/settlement-source difference from an IEM METAR archive artifact for airport ASOS stations. Distinguishing those would require an independent official daily max/continuous ASOS or LCD-style source for the same station-days, or raw station products showing the exact observation stream used to populate each CLI maximum.

## 3. Boundary-Distance Restricted Gates

Distance is `abs(unrounded_metar_max_f - threshold_f)` for each threshold case. Retained fraction is reported against all evaluated city-threshold cases; city-days with at least one retained threshold are also shown because every evaluated day can still have a far-from-boundary threshold.

| Cut | City | Retained cases | Case fraction | City-days retained | City-day fraction | Agreement | Wilson 95% lower | Verdict |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| >0.5 F | LAX | 5460/7280 | 0.750000 | 1820/1820 | 1.000000 | 1.000000 | 0.999297 | PASSED |
| >0.5 F | MDW | 5478/7304 | 0.750000 | 1826/1826 | 1.000000 | 0.998357 | 0.996880 | PASSED |
| >0.5 F | MIA | 5439/7252 | 0.750000 | 1813/1813 | 1.000000 | 0.999816 | 0.998959 | PASSED |
| >0.5 F | NYC | 5442/7256 | 0.750000 | 1814/1814 | 1.000000 | 0.999265 | 0.998111 | PASSED |
| >0.5 F | SFO | 5397/7196 | 0.750000 | 1799/1799 | 1.000000 | 0.999074 | 0.997833 | PASSED |
| >1.0 F | LAX | 4301/7280 | 0.590797 | 1820/1820 | 1.000000 | 1.000000 | 0.999108 | PASSED |
| >1.0 F | MDW | 4235/7304 | 0.579819 | 1826/1826 | 1.000000 | 0.997875 | 0.995966 | PASSED |
| >1.0 F | MIA | 4358/7252 | 0.600938 | 1813/1813 | 1.000000 | 0.999771 | 0.998701 | PASSED |
| >1.0 F | NYC | 4443/7256 | 0.612321 | 1814/1814 | 1.000000 | 0.999325 | 0.998017 | PASSED |
| >1.0 F | SFO | 4242/7196 | 0.589494 | 1799/1799 | 1.000000 | 0.999057 | 0.997578 | PASSED |
| >2.0 F | LAX | 2481/7280 | 0.340797 | 1820/1820 | 1.000000 | 1.000000 | 0.998454 | PASSED |
| >2.0 F | MDW | 2409/7304 | 0.329819 | 1826/1826 | 1.000000 | 0.997509 | 0.994576 | PASSED |
| >2.0 F | MIA | 2545/7252 | 0.350938 | 1813/1813 | 1.000000 | 1.000000 | 0.998493 | PASSED |
| >2.0 F | NYC | 2629/7256 | 0.362321 | 1814/1814 | 1.000000 | 0.999620 | 0.997848 | PASSED |
| >2.0 F | SFO | 2443/7196 | 0.339494 | 1799/1799 | 1.000000 | 0.999181 | 0.997020 | PASSED |

## Original Unrestricted Gate

| City | Cases | Matches | Mismatches | Agreement rate | Wilson 95% lower | Verdict |
|---|---:|---:|---:|---:|---:|---|
| LAX | 7280 | 6938 | 342 | 0.953022 | 0.947918 | FAILED |
| MDW | 7304 | 6928 | 376 | 0.948521 | 0.943214 | FAILED |
| MIA | 7252 | 6980 | 272 | 0.962493 | 0.957870 | FAILED |
| NYC | 7256 | 7249 | 7 | 0.999035 | 0.998010 | PASSED |
| SFO | 7196 | 6850 | 346 | 0.951918 | 0.946729 | FAILED |

