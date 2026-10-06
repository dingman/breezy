# F13 Phase A0 feasibility probe (2026-10-06 ~01:57–02:01Z)

Read-only public-HTTPS probe by an Explore agent: 59 GET/HEAD requests, no credentials, no venue hosts. Plan: `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md` (+ r3.1/r3.2). The agent's report is quoted below unedited; the coordinator rulings that follow are binding for F13-C1.

## Coordinator rulings from A0 (F13-A0-R1..R6)

- **A0-R1 (IEM pacing).** The new AFOS and LAV methods use a new `IEM_AFOS_LAV_MIN_INTERVAL_NS` of at least 4 s. `IEM_MIN_INTERVAL_NS` (1 s) and the existing MOS backfill are unchanged unless a throttle body is observed on that path. That would be a separate, evidence-backed change. The throttle body `Too many requests from your IP address` is an H3-class refusal: it never counts as data, and the run backs off and alerts.
- **A0-R2 (PFM key; closes OPEN-2 for PFM).** PFM rows are keyed by `(WFO, point_name)` from a closed five-entry map:
  - KNYC OKX `Central Park-New York NY`;
  - KLAX LOX `Los Angeles Airport CA`;
  - KMDW LOT `Chicago Midway Airport-Cook IL`;
  - KSFO MTR `San Francisco Airport-San Mateo CA`;
  - KMIA MFL `Miami-Miami Dade FL`.

  KMIA is **inferred**: B0 confirms it by lat/lon (25.82N 80.28W against KMIA). The zone code is recorded but never used as a key. `ArchiveRequest` mapping: `source=us-pfm-afos`, `station=<ICAO>`, `product=pfm`, `model=<WFO>`. The pre-2004 zone-less format is a pre-registered source break, and the backfill starts no earlier than 2021.
- **A0-R3 (LAMP live).** C1 polls NOMADS `lmp.YYYYMMDD/lmp.tHH30z.lavtxt.ascii` (HTTP/1.1) once per hour, plus `lavtxt_ext` for hours 26–38. NOMADS keeps two days, so polling must be continuous. The quarter-hour runs are out of scope. The daily max is derived from hourly `TMP` over the climate-day LST window. A window not fully covered is MISSING (r3 test). The measured lag is 6–10 min after :30.
- **A0-R4 (LAMP archive; replaces the "2026 gap" premise).** MDL publishes monthly `lmp_lavtxt.YYYYMM.HHMMz.gz` files through 2026-09, about 1–5 weeks after month end, plus yearly tars for 2006–2025. So `us-lamp-mdl` covers 2026 Jan–Sep, and IEM LAV is a cross-check and gap-fill only. Missing days are real (the 202609 0130z file has 26 of 30 days). They are MISSING, never imputed. The H2 tar handler applies to the yearly tars. The monthly `.gz` files are concatenated text, so they need a streamed gzip line reader with the same byte caps. Allowed MDL host: `lamp.mdl.nws.noaa.gov` (exact). NOMADS host: `nomads.ncep.noaa.gov` (exact).
- **A0-R5 (NBP observation).** The NBP text bulletin is on NOMADS (`blend.YYYYMMDD/HH/text/blend_nbptx.tHHz`, 26 MB, measured lag 1h16m for 00Z). The repo transport uses `noaa-nbm-grib2-pds` (S3) with a NOMADS fallback. R29 (reuse the unmodified `fetch_nbp_bulletin`) stands. A0 did not contact the S3 bucket because it was not on the probe list, so B0 confirms the S3 key and lag from the node catalog (R29).
- **A0-R6 (KNYC MOS).** IEM serves GFS MOS for KNYC from at least 2005, and LAV from 2020-01-01 at the earliest (first rows between 2020-01-01 and 2021-06-01). The backfill window is ≥ 2021 for every source, which keeps folds within NBM versions.

## Probe report (verbatim)

I made 59 of the 60 allowed requests. I wrote no files: the brief allowed scratch output, but read-only mode forbids creating files, so I processed every download in memory. All times are UTC and the probe ran at 2026-10-06 ~01:57–02:01.

Two findings matter most for C1. PFM zone codes are not unique per station, so points must be keyed by point name. And IEM throttled me at about 1.2 s between requests, faster than its 1 request per second guideline.

## Feasibility table

| # | Item | Status |
|---|---|---|
| 1 | LAMP live product | VERIFIED |
| 2 | LAMP archive | VERIFIED |
| 3 | IEM LAV | VERIFIED |
| 4 | PFM via IEM AFOS | VERIFIED (KMIA point is an inference) |
| 5 | GFS MOS (MAV) for KNYC | VERIFIED |
| 6 | IEM rate-limit policy | NOT-FOUND as a written policy; throttle observed |
| 7 | NBP on noaa-nbm-pds | NOT-FOUND there; VERIFIED on NOMADS |

## 1. LAMP live product
- **Where:** `https://nomads.ncep.noaa.gov/pub/data/nccf/com/lmp/prod/lmp.YYYYMMDD/lmp.tHHMMz.lavtxt.ascii`. It is a plain ASCII station bulletin.
  - NOMADS needs `--http1.1`; over HTTP/2 it fails with a malformed content-length header.
  - Only two days are kept (`lmp.20261005/`, `lmp.20261006/`).
- **Runs:** every 15 minutes. The hourly runs at HH30 are the full ones: lavtxt.ascii is 4.3 MB (hours 1–25, all five stations present), `lavtxt_ext.ascii` covers hours 26–38, and there is also BUFR and GRIB2. The :00, :15 and :45 runs are 648K files.
- **Stations:** all five are in t0130z:
  - `KNYC   GFS LAMP GUIDANCE  10/06/2026  0130 UTC`
  - KMIA, KMDW, KLAX and KSFO have the same header line.
- **Max temperature:** there is no explicit max/min row, only hourly `TMP`, e.g. `TMP  59 57 57 55 ...`. The climate-day max has to be derived from the hourly temps (inferred).
- **Lag** (Last-Modified vs the run's :30 time):

| Run | Last-Modified | Lag |
|---|---|---|
| t0030z | `Tue, 06 Oct 2026 00:40:04 GMT` | 10m04s |
| t0130z | `01:36:05` | 6m05s |
| t2330z (10-05) | `23:35:44` | 5m44s |

- MDL also publishes a "latest" copy at `https://lamp.mdl.nws.noaa.gov/lamp/Data/bull_1hr/lavlamp.latest.simpbull.f001-f038.txt` (found as a link, not fetched).

## 2. LAMP archive
- `noaa-lamp-pds` does not exist: `NoSuchBucket`.
- The archive is at `https://lamp.mdl.nws.noaa.gov/lamp/Data/archives/`.
- **Yearly tars:** `lmp_lavtxt.YYYY.tar` for 2006–2025, e.g. `lmp_lavtxt.2025.tar 2026-01-08 20:06 3.8G`.
- **Monthly files:** `lmp_lavtxt.YYYYMM.HHMMz.gz`, 96 per month (24 hours × 4 quarter-hours), running from `lmp_lavtxt.200608.03z.gz` to `lmp_lavtxt.202609.2345z.gz`. **2026 exists, January to September.**
  - Each month is posted at the start of the next, e.g. 202609 files are dated `2026-10-01 14:28`.
- **Tar members:** I read the first header with a ranged GET of 1024 bytes. The first member is `lmp_lavtxt.202501.0000z.gz`, size 486846, mtime 1738594963 (2025-02-03 15:02). So each tar is a bundle of the monthly gz files.
- **One sample file:** `lmp_lavtxt.202609.0130z.gz` returned HTTP 200 with `Last-Modified: Thu, 01 Oct 2026 14:28:17 GMT`. It is 10.97 MB gz, 119 MB unpacked, and is concatenated text, not a tar.
  - It has 60138 station blocks covering only **26 distinct dates** in September; 4 days are missing.
  - It has 26 blocks for each of the five stations.

## 3. IEM LAV
- Both endpoints work:
  - `https://mesonet.agron.iastate.edu/api/1/mos.json?station=KLAX&model=LAV` → 200
  - `/cgi-bin/request/mos.py?station=KNYC&model=LAV&sts=...&ets=...&format=csv` → 200
- Sample row: `2026-10-05 00:00:00,2026-10-05 01:00:00,LAV,57,54,OV,...,KNYC`.
- Runs are hourly, labelled HH:00, with 38 forecast rows each. That HH:00 label probably stands for the HH30 run (inferred).
- **Coverage start (KNYC):** 0 rows on 2020-01-01, 38 rows on 2021-06-01. So it starts somewhere between those dates; I did not narrow it further.

## 4. PFM via IEM AFOS
- **URL pattern:** `https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=PFM{WFO}&limit=1&fmt=text`. Adding `sdate=...&order=asc` gives history.
- **Cadence list:** `https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil=PFMLOT&date=YYYY-MM-DD`.
- **Latest headers:**

| WFO | Header | Local issue time |
|---|---|---|
| OKX | `FOUS51 KOKX 051901` | `301 PM EDT` |
| LOX | `FOUS56 KLOX 052152` | `252 PM PDT` |
| LOT | `FOUS53 KLOT 060156` | `856 PM CDT` |
| MFL | `FOUS52 KMFL 051821` | `221 PM EDT` |
| MTR | `FOUS56 KMTR 060100` | `600 PM PDT` |

- **Point map:**

| Station | WFO | Zone line | Point name, location |
|---|---|---|---|
| KNYC | OKX | `NYZ072-060800-` | `Central Park-New York NY`, 40.78N 73.97W |
| KLAX | LOX | `CAZ366-061100-` | `Los Angeles Airport CA`, 33.94N 118.39W |
| KMDW | LOT | `ILZ104-060900-` | `Chicago Midway Airport-Cook IL`, 41.78N 87.76W |
| KSFO | MTR | `CAZ508-061100-` | `San Francisco Airport-San Mateo CA`, 37.62N 122.38W |
| KMIA | MFL | `FLZ074-060800-` | `Miami-Miami Dade FL`, 25.82N 80.28W |

  - KMIA is an inference: the point is not labelled as the airport.
  - **Zone codes are shared:** ILZ104 is both O'Hare and Midway, CAZ508 is SFO, Hayward and Oakland, CAZ368 is Downtown LA and Long Beach. Keying on zone alone would be wrong.
- **Cadence:** LOT issued about hourly on 2026-10-05, at :15 past plus extra issues at 0100, 0131, 0856, 1135 and 2056 (28 entries). I did not measure cadence for the other WFOs.
- **History:** the earliest PFMOKX is `FOUS51 KOKX 280940` (2003-10-28). That older format has no zone code: `CENTRAL PARK-282130-`, so there is a format break.

## 5. GFS MOS (MAV) for KNYC
- `mos.py?station=KNYC&model=GFS` returned 64 rows for 2026-10-05 (00, 06 and 12Z runs) and 63 rows for 2005-01-01.
- History therefore goes back to at least 2005-01-01; I did not probe earlier.

## 6. IEM rate limit
- `disclaimer.php` has no rate-limit statement.
- **Observed throttle:** at about 1.2 s between requests (roughly the 8th request in about 10 s), IEM returned the body `Too many requests from your IP address, slow down.` I did not capture the status code. Waiting 3–4 s between requests worked fine.

## 7. NBP
- **noaa-nbm-pds:** the bucket root has only versioned prefixes (`blendv3.2/` … `blendv5.0/`). `blendv5.0/` holds `alaska/`, `conus/`, `puertoRico/`, … (regional), and the old `blend.YYYYMMDD/` path has nothing (`KeyCount 0`). I found no NBP text bulletin there.
- **NOMADS has it:** `https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20261006/00/text/blend_nbptx.t00z` returned `Last-Modified: Tue, 06 Oct 2026 01:15:47 GMT` (26 MB). That is a lag of **1h15m47s** after the 00Z cycle.
- The repo's NBP code reads from a different bucket, `S3_QUANTILE_HOST = "noaa-nbm-grib2-pds.s3.amazonaws.com"` (`/home/jon/breezy/src/breezy/ingest/nbm_quantile_transport.py:97`). It is not on the allowed list, so I did not contact it.

## Repo constants
`/home/jon/breezy/scripts/venue/iem_mos_probe_transport.py`:
- `IEM_HOST = "mesonet.agron.iastate.edu"`, `IEM_BASE_URL = f"https://{IEM_HOST}"`
- `IEM_MOS_PATH = "/cgi-bin/request/mos.py"`, `IEM_MIN_INTERVAL_NS = 1_000_000_000`
- `IEM_MOS_STATION_ORDER = ("KLAX","KMDW","KMIA","KSFO")` (no KNYC), `IEM_MOS_MODEL_ORDER = ("NBS","GFS")` (no LAV)

New paths could sit beside these, e.g. `/cgi-bin/afos/retrieve.py` and `/api/1/nws/afos/list.json`.

## Blockers for C1
1. **IEM pacing:** the existing 1 s minimum interval triggered throttling, so it probably needs to be at least 3 s (inferred from one event).
2. **PFM key:** OPEN-2 needs a point-name field. Zone plus WFO is not unique.
3. **LAMP live retention:** NOMADS keeps only 2 days, so C1 has to poll continuously. The monthly archive arrives about 1–5 weeks after the month ends.
4. **LAMP max temperature:** there is no explicit max row; it must be derived from hourly TMP, and the hourly :30 runs only reach 38 h.
5. **LAMP archive gaps:** the September 2026 0130z file covers only 26 of 30 days.
