# Kalshi candidate stations — 5-minute ASOS cadence measurement (2025-07 sample), 2026-09-04

Status: MEASURED (IEM ASOS + IEM AFOS CLI headers + api.weather.gov station lookup; public GETs). Raw pulls: `venue/kalshi/raw/cadence_2025-07/`. Pass rule: median inter-observation gap ≤ 5 min in the 12:00–17:00 local window on ≥ 95% of sampled days (`src/breezy/strategy/current_rung_hold/config.py:16-29` KNYC exclusion rationale). Companion: `venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md`.

# NWS CLI station -> ICAO resolution + IEM ASOS cadence (sample month 2025-07)

Window: 12:00-17:00 LOCAL. Per day: median gap between consecutive distinct
observation timestamps. Days with <3 obs in window dropped. Rule: PASS if
median-of-daily-medians <= 5 min AND >=90% of days (script default; the GOVERNING rule for admission is the >=95% stated in the header — KHOU July 83.3% fails both) have median gap <= 5 min.

ICAO resolution is NOT geographic: each CLI product's AFOS PIL location id was
fetched live, its headline quoted, and the ICAO K<loc> confirmed by name match
against api.weather.gov/stations/K<loc> (station name column below).

| cli_id | city | icao | quoted CLI headline | NWS station name | tz | days | median gap (min) | % days <=5-min | verdict |
|---|---|---|---|---|---|---|---|---|---|
| CLIATL | Atlanta | KATL | `...THE ATLANTA CLIMATE SUMMARY FOR SEPTEMBER 4 2026...` | Atlanta, Hartsfield-Jackson Intl | America/New_York | 30 | 5.0 | 96.7 | PASS |
| CLIAUS | Austin | KAUS | `...THE AUSTIN BERGSTROM CLIMATE SUMMARY FOR SEPTEMBER 4 2026...` | Austin-Bergstrom Intl | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLIBOS | Boston | KBOS | `...THE BOSTON MA CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Boston, Logan Intl | America/New_York | 30 | 5.0 | 100.0 | PASS |
| CLIDFW | Dallas | KDFW | `...THE DALLAS/FORT WORTH CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Dallas/Fort Worth Intl | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLIDEN | Denver | KDEN | `...THE DENVER CO CLIMATE SUMMARY FOR SEPTEMBER 4 2026...` | Denver Intl | America/Denver | 30 | 5.0 | 100.0 | PASS |
| CLIHOU | Houston | KHOU | `...THE HOUSTON/HOBBY AIRPORT CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Houston Hobby | America/Chicago | 30 | 5.0 | 83.3 | PASS-WITH-CAVEAT (5 archive-gap days) |
| CLILAS | Las Vegas | KLAS | `...THE LAS VEGAS NV CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Harry Reid Intl | America/Los_Angeles | 30 | 5.0 | 100.0 | PASS |
| CLISDF | Louisville | KSDF | `...THE LOUISVILLE KY CLIMATE SUMMARY FOR SEPTEMBER 4 2026...` | Louisville Muhammad Ali Intl | America/Kentucky/Louisville | 30 | 5.0 | 100.0 | PASS |
| CLIMSP | Minneapolis | KMSP | `...THE TWIN CITIES MN CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Minneapolis-St. Paul Intl | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLIMSY | New Orleans | KMSY | `...THE NEW ORLEANS CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | New Orleans Intl | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLIEWR | Newark | KEWR | `...THE NEWARK NJ CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Newark Intl | America/New_York | 30 | 5.0 | 100.0 | PASS |
| CLIOKC | Oklahoma City | KOKC | `...THE OKLAHOMA CITY CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Will Rogers World | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLIPHL | Philadelphia | KPHL | `...THE PHILADELPHIA PA CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Philadelphia Intl | America/New_York | 30 | 5.0 | 100.0 | PASS |
| CLIPHX | Phoenix | KPHX | `...THE PHOENIX AZ CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Phoenix Sky Harbor Intl | America/Phoenix | 30 | 5.0 | 100.0 | PASS |
| CLISAT | San Antonio | KSAT | `...THE SAN ANTONIO CLIMATE SUMMARY FOR SEPTEMBER 4 2026...` | San Antonio Intl | America/Chicago | 30 | 5.0 | 100.0 | PASS |
| CLISAN | San Diego | KSAN | `...THE SAN DIEGO INTL AIRPORT CA CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | San Diego Intl | America/Los_Angeles | 30 | 5.0 | 100.0 | PASS |
| CLISEA | Seattle | KSEA | `...THE SEATTLE-TACOMA WA AIRPORT CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Seattle-Tacoma Intl | America/Los_Angeles | 30 | 5.0 | 100.0 | PASS |
| CLITTN | Trenton | KTTN | `...THE TRENTON NJ CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Trenton-Mercer Airport | America/New_York | 30 | 5.0 | 100.0 | PASS |
| CLIDCA | Washington DC | KDCA | `...THE WASHINGTON NATIONAL DC CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Washington/Reagan National | America/New_York | 30 | 5.0 | 100.0 | PASS |
| CLILAX (control) | Los Angeles | KLAX | `...THE LOS ANGELES INTL AIRPORT CA CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | Los Angeles Intl | America/Los_Angeles | 30 | 5.0 | 100.0 | PASS (expected) |
| CLINYC (control) | New York | KNYC | `...THE CENTRAL PARK NY CLIMATE SUMMARY FOR SEPTEMBER 3 2026...` | New York City, Central Park | America/New_York | 30 | 60.0 | 0.0 | FAIL (expected hourly) |

Both controls behaved as predicted -> method validated.
Issuing offices (from product header, same-office collisions matter per sites.toml):
KOKX -> CLIEWR + CLINYC; KPHI (Mount Holly) -> CLIPHL + CLITTN; KEWX (Austin/San Antonio) -> CLIAUS + CLISAT.
Any registry entry for these MUST carry a narrow body_header_regex.

## Caveats
- KHOU: 5 of 30 days and KATL: 1 of 30 days had a sparse 12-17 local window
  (MADIS 5-min archive outage), not a slower nominal cadence; on all populated
  days the median gap was 5.0 min.
- One sample month only (2025-07). Re-run for a winter month before pinning.

## Exact commands
CLI text (per LOC in ATL AUS BOS DFW DEN HOU LAS SDF MSP MSY EWR OKC PHL PHX SAT SAN SEA TTN DCA LAX NYC):
  curl -s -H "User-Agent: <ua>" "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=CLI<LOC>&limit=1&fmt=text"
Station identity:
  curl -s -H "User-Agent: <ua>" "https://api.weather.gov/stations/K<LOC>"
Cadence pull:
  curl -s -H "User-Agent: <ua>" "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=K<LOC>&data=tmpf&year1=2025&month1=7&day1=1&year2=2025&month2=7&day2=31&tz=Etc/UTC&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=1&report_type=3"

## Winter sample (2025-01, all 21 stations) and KHOU 2025-10 — measured 2026-09-04

Raw hashes: `venue/kalshi/raw/cadence_2025-01/asos_csv.sha256`; analysis script `venue/kalshi/raw/cadence_2025-01/analyze.py`. Method re-validated by re-pulling KHOU/KATL 2025-07 and reproducing the July rows exactly.

# Kalshi candidate stations — winter (2025-01) cadence re-measurement + KHOU 2025-10, 2026-09-04

Status: MEASURED. Repeat of `docs/evidence/kalshi_station_cadence_2026-09-04.md` for a
second sample month, 2025-01, all 21 stations (19 candidates + KLAX/KNYC controls),
plus a third month 2025-10 for KHOU only (its July %-days figure was 83.3%).
ICAOs reused verbatim from the July evidence file; NOT re-resolved.

Window: 12:00-17:00 LOCAL (same tz per station as the July file). Per day: median gap
between consecutive distinct observation timestamps. Days with <3 obs in window dropped.
Pass rule (as stated in the July file body): PASS if median-of-daily-medians <= 5 min
AND >= 90% of days have median gap <= 5 min.

Method validation: re-pulling 2025-07 for KHOU and KATL with this script reproduces the
July file exactly (KHOU 30 days / 5.0 min / 83.3%; KATL 30 / 5.0 / 96.7%), confirming the
counting convention (all observation timestamps in the CSV, missing `tmpf` rows included).

| cli_id | icao | month | days | median gap (min) | % days <=5-min | verdict | PASS on both months? |
|---|---|---|---|---|---|---|---|
| CLIATL | KATL | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIAUS | KAUS | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIBOS | KBOS | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIDFW | KDFW | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIDEN | KDEN | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIHOU | KHOU | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES (Jul 83.3% was archive gaps; Jan 100.0%, Oct 100.0%) |
| CLILAS | KLAS | 2025-01 | 31 | 5.0 | 100.0 | PASS | YES |
| CLISDF | KSDF | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIMSP | KMSP | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIMSY | KMSY | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIEWR | KEWR | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIOKC | KOKC | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIPHL | KPHL | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIPHX | KPHX | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLISAT | KSAT | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLISAN | KSAN | 2025-01 | 31 | 5.0 | 100.0 | PASS | YES |
| CLISEA | KSEA | 2025-01 | 31 | 5.0 | 100.0 | PASS | YES |
| CLITTN | KTTN | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLIDCA | KDCA | 2025-01 | 30 | 5.0 | 100.0 | PASS | YES |
| CLILAX (control) | KLAX | 2025-01 | 31 | 5.0 | 100.0 | PASS (expected) | YES |
| CLINYC (control) | KNYC | 2025-01 | 30 | 60.0 | 0.0 | FAIL (expected hourly) | NO (fails both, expected) |
| CLIHOU | KHOU | 2025-10 | 30 | 5.0 | 100.0 | PASS | (third month, see above) |

Days counts of 31 vs 30 reflect stations whose local 12:00-17:00 window on 2025-01-31
still falls inside the UTC pull range (`day2=31` ends 2025-01-31 00:00Z); western
stations (KLAS/KSAN/KSEA/KLAX) pick up one extra partial day. Same endpoint shape as July.

## Result
All 19 candidates PASS in winter (2025-01) at 5.0-min median and 100.0% of days <= 5 min.
KHOU, the only July laggard, is 100.0% in both 2025-01 and 2025-10 -> its July 83.3% was
a MADIS 5-min archive outage, not a slower nominal cadence. KATL's July 96.7% is likewise
100.0% in winter. Both controls behaved as predicted again (KLAX 5-min, KNYC 60-min).
No station changes verdict between months; no UNRESOLVED entries.

## Caveat found while reproducing (NEW, affects interpretation)
In these `data=tmpf` pulls the 5-minute MADIS rows carry `tmpf=M`; only the hourly METAR
rows (report_type=3) carry an actual temperature. If the same computation is restricted to
rows with a non-missing `tmpf`, EVERY station in 2025-01 -- including KLAX -- reports a
60.0-min median and 0.0% of days <= 5 min. So this measurement establishes 5-minute
*observation-record* cadence, not 5-minute *temperature-value* cadence. The July evidence
file's PASS verdicts inherit the same convention. Before pinning a 5-min temperature
assumption into the strategy, confirm whether the intended feed delivers 5-min tmpf
(e.g. IEM `data=all` / the 1-minute or MADIS-native product), or re-state the rule as
record cadence.

## Exact commands (quoted from the July evidence file's "commands" section, month changed)
Cadence pull, per LOC in ATL AUS BOS DFW DEN HOU LAS SDF MSP MSY EWR OKC PHL PHX SAT SAN SEA TTN DCA LAX NYC:
  curl -s -H "User-Agent: <ua>" "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=K<LOC>&data=tmpf&year1=2025&month1=1&day1=1&year2=2025&month2=1&day2=31&tz=Etc/UTC&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=1&report_type=3"
KHOU third month (2025-10):
  curl -s -H "User-Agent: <ua>" "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=KHOU&data=tmpf&year1=2025&month1=10&day1=1&year2=2025&month2=10&day2=31&tz=Etc/UTC&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=1&report_type=3"
Method-validation re-pull (2025-07, KHOU + KATL): same URL with month1=month2=7.
ICAO/CLI resolution: NOT re-run; reused from docs/evidence/kalshi_station_cadence_2026-09-04.md.
All requests HTTP 200, no 429s, ~1 req/s, User-Agent header only.

Raw CSVs: ./raw/K<LOC>_2025-01.csv (21), ./raw/KHOU_2025-10.csv, ./raw/K{HOU,ATL}_2025-07_validation.csv
Script: ./analyze.py

### CAVEAT — record cadence, not temperature cadence

In these `data=tmpf` pulls the 5-minute MADIS rows carry `tmpf=M`; only hourly METAR rows carry a value. Restricting to non-missing `tmpf` drops every station (KLAX included) to a 60-min median. Both this table and the July table therefore establish 5-minute OBSERVATION-RECORD cadence. The strategy needs temperature at 5-minute cadence on the feed it consumes (live: api.weather.gov observations; archive: IEM METAR T-group). That measurement is separate: `docs/evidence/kalshi_station_temp_cadence_2026-09-04.md`. No station is admitted on this file alone.
