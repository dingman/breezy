# Kalshi candidate stations — temperature-bearing 5-minute cadence on BOTH feeds (live 2026-09-03; archive 2025-07-01..07), measured 2026-09-04

Status: MEASURED. Supersedes the record-cadence caveat in `kalshi_station_cadence_2026-09-04.md`. Live feed = `api.weather.gov/stations/{icao}/observations` (non-null temperature); archive feed = IEM ASOS METAR remark T-group (what `mb_current_rung_edge_study.py` consumes via `settlement_alignment_study.metar_temperatures`). Raw hashes and analysis scripts: `venue/kalshi/raw/temp_cadence_2026-09-03/` (raw JSON/CSV retained in the session scratchpad, not committed).

# Temperature cadence at 5 min: LIVE (NWS API) vs ARCHIVE (IEM METAR) — 2026-09-04

Window: 12:00–17:00 **LST** (fixed standard offset, repo `climate_day` convention; no DST).
LIVE day = 2026-09-03. ARCHIVE days = 2025-07-01..2025-07-07 (7 days).
Verdicts: LIVE PASS = median gap ≤5 min AND ≥50 obs in the 5 h window. ARCHIVE PASS = median gap ≤5 min.

| icao | live temp obs in 5h | live median gap | live verdict | archive temp rows/day | archive median gap | archive verdict |
|---|---|---|---|---|---|---|
| KATL | 65 | 5.0 min | PASS | 65.1 | 5.0 min | PASS |
| KAUS | 65 | 5.0 min | PASS | 66.7 | 5.0 min | PASS |
| KBOS | 59 | 5.0 min | PASS | 59.4 * | 5.0 min | PASS |
| KDFW | 61 | 5.0 min | PASS | 64.0 | 5.0 min | PASS |
| KDEN | 6 | 60.0 min | FAIL | 64.1 | 5.0 min | PASS |
| KHOU | 70 | 5.0 min | PASS | 26.0 † | 5.0 min | PASS |
| KLAS | 64 | 5.0 min | PASS | 65.6 | 5.0 min | PASS |
| KSDF | 65 | 5.0 min | PASS | 65.6 | 5.0 min | PASS |
| KMSP | 71 | 5.0 min | PASS | 59.7 | 5.0 min | PASS |
| KMSY | 65 | 5.0 min | PASS | 65.7 | 5.0 min | PASS |
| KEWR | 65 | 5.0 min | PASS | 65.7 | 5.0 min | PASS |
| KOKC | 65 | 5.0 min | PASS | 63.0 | 5.0 min | PASS |
| KPHL | 65 | 5.0 min | PASS | 67.1 | 5.0 min | PASS |
| KPHX | 65 | 5.0 min | PASS | 65.1 | 5.0 min | PASS |
| KSAT | 66 | 5.0 min | PASS | 66.4 | 5.0 min | PASS |
| KSAN | 66 | 5.0 min | PASS | 65.4 | 5.0 min | PASS |
| KSEA | 61 | 5.0 min | PASS | 64.4 | 5.0 min | PASS |
| KTTN | 65 | 5.0 min | PASS | 65.6 | 5.0 min | PASS |
| KDCA | 65 | 5.0 min | PASS | 66.3 | 5.0 min | PASS |
| KLAX | 64 | 5.0 min | PASS | 65.1 | 5.0 min | PASS |
| KNYC | 5 | 60.0 min | FAIL | 5.0 | 60.0 min | FAIL |

\* **KBOS**: its 5-minute MADISHF rows carry a SHORT remark T-group `T0300` (sign + 3 digits,
temperature only, no dewpoint) and `tmpf=M`. The specified regex `\bT[01]\d{3}[01]\d{3}\b`
matches only 8-digit groups, so it sees **7.1 rows/day, median 56 min → FAIL**. Admitting
`\bT[01]\d{3}\b` recovers **59.4 rows/day, median 5.0 min → PASS**. Same short form also lifts
KEWR 49.4→65.7, KDEN 62.6→64.1, KLAS 63.6→65.6, KSEA 63.0→64.4, KPHL 65.7→67.1 (partial-day mixes).
Consequence: `metar_temperatures` / `parse_metar_t_group` in
`/home/jon/breezy/scripts/analysis/settlement_alignment_study.py` drops these rows.

† **KHOU**: cadence is 5 min but the 5-minute feed *stops* mid-corpus. Per-day counts
2025-07-01..07: 66, 65, 31, 5, 5, 5, 5 — hourly-only from 07-04 on. Coverage gap, not a cadence failure.

**KDEN**: LIVE FAIL is real, not an artifact. The 2026-09-03 payload has 6 features total in the
window (:53 METARs + one :28 SPECI); no 5-minute rows. Yet its ARCHIVE 2025-07 cadence is 5 min.
Live 5-minute publication for KDEN on `api.weather.gov` appears to have stopped — recheck before relying on it.

**KNYC**: FAIL on both feeds (hourly :51 only), confirming `observation_source_latency_2026-09-04.md`.

Precision caveat (unchanged from prior evidence): LIVE 5-minute rows carry integer °C with empty
`rawMessage`; only the :5x METAR carries tenths. ARCHIVE 5-minute rows DO carry tenths via the
remark T-group. So archive 5-min temps are rung-exact; live 5-min temps bound R(t) to ~1.8 °F.

## Exact commands

LIVE (per ICAO, 0.6 s spacing, headers `User-Agent: breezy-research/1.0 (jon@gopoint.com)`,
`Accept: application/geo+json`):

    https://api.weather.gov/stations/KATL/observations?start=2026-09-03T17:00:00Z&end=2026-09-03T22:00:00Z&limit=500

(start/end = 12:00/17:00 at each station's standard UTC offset: -5 ATL BOS SDF EWR PHL TTN DCA NYC;
-6 AUS DFW HOU MSP MSY OKC SAT; -7 DEN PHX; -8 LAS LAX SAN SEA.)

ARCHIVE (per ICAO, 1.1 s spacing), mirroring `settlement_alignment_study.asos_url` plus `data=tmpf`:

    https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=KATL&data=metar&data=tmpf&year1=2025&month1=6&day1=30&year2=2025&month2=7&day2=9&tz=Etc%2FUTC&format=onlycomma&latlon=no&direct=no&report_type=1&report_type=2

Row counted if METAR matches `\bT[01]\d{3}[01]\d{3}\b` or `\bT[01]\d{3}\b`, or `tmpf` is not `M`.
No 429/503 was returned by either host; all 42 requests succeeded on first attempt. No station UNRESOLVED.

## Raw artifacts

- `live/{ICAO}.json` — 21 raw NWS GeoJSON payloads
- `archive/{ICAO}.csv` — 21 raw IEM CSVs (2025-06-30..2025-07-09)
- `live_summary.json`, `archive_summary.json` (strict 8-digit), `archive_summary2.json` (both forms + per-day)
- `live.py`, `arch.py` — the fetch/measure scripts

## KDEN recheck — 2026-09-04 12:00–21:30 UTC (live NWS feed, temperature-bearing observations)

| icao | temp obs | median gap | span | verdict |
|---|---|---|---|---|
| KDEN | 8 | 60.0 min | 12:53–19:53 | FAIL (second consecutive day hourly-only) |
| KLAX (control) | 115 | 5.0 min | 12:00–20:45 | PASS |

Two consecutive live days (09-03, 09-04) with no 5-minute rows while the 2025 archive is clean 5-min: KDEN's live 5-minute publication has stopped. Status: **EXCLUDED from the Kalshi family candidate set unless live 5-min temperature publication is observed again on ≥2 days** (re-run this check; the archive alone cannot admit it because the live stale bound of 50 min is miscalibrated for an hourly feed — the KNYC rule, `config.py:16-29`).
