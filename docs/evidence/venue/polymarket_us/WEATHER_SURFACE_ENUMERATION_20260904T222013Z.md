# Polymarket.us weather-market surface enumeration — 20260904T222013Z

**Provenance.** Public gateway `https://gateway.polymarket.us` (unauthenticated; no credentials loaded or sent), official `polymarket_us` SDK 0.1.2, GET only. Window 2026-09-04T22:20:13Z → 22:24:34Z. **80 requests total** (74 main walk + 6 low-series probe), ≤1 req/s, **0 errors, 0× 429, 0× 403**. Page size used: `limit=500` (`limit=1000` returned 500 → 500 is the server cap). Raw pages total 66 MB (> 2 MB) so only per-market summary rows are stored (`*_market_summary_rows.json`, 16,165 rows: slug, title, category, status, closed, endDate, sources). Request log with paths+params only: `*_request_log.json`. Produced by `polymarket-us-discovery`; every claim below is **provisional: true** (1 session, needs independent sign-off).

**Question.** Does `tc-temp-<city><high|low>-<YYYY-MM-DD>-<bounds>f` × {nyc, sfo, mia, mdw, lax} (`symbology._WEATHER_SLUG_RE` + `sites.toml`) cover every weather-related market the venue lists today?
**Answer.** YES for everything observable read-only. All 3,743 `climate` markets parse under the repo grammar and all fall in the five registry cities; zero weather-related markets exist outside `climate`; the venue lists **daily HIGH only** — the five `weather-daily-low-*` series exist but hold 0 events.

## (A) Counts by measure × city (all `category=climate`, `marketType=futures`)

| measure | NYC | SFO | MIA | MDW | LAX | total | open now |
|---|---|---|---|---|---|---|---|
| daily high temp (`tc-temp-<city>high-…`) | 750 | 750 | 749 | 750 | 744 | **3,743** | 60 (2026-09-04: 30, 2026-09-05: 30) |
| daily low temp | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| precipitation / snow / storm / wind / other | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Station-days: 624 (623 with a 6-rung ladder, 1 with 5 — `mia 2026-07-09`). Dates 2026-04-22 → 2026-09-05 (125 listed of 137 calendar days). Every `question` begins "Highest temperature in …"; 0/3,743 mention "low".

## (B) Weather markets the repo grammar / city filter would NOT discover

**None found.** `parse_weather_slug` returned a record for 3,743/3,743 climate slugs, all with city ∈ {nyc, sfo, mia, mdw, lax}. Across the full corpus of **16,165 distinct markets** (climate 3,743; sports 9,227; politics 2,000 sampled; culture 1,000 sampled; crypto 57; geopolitics 15; science 14) keyword matching (temperature, high/low temp, rain, precipitation, snow(fall), hurricane, storm, tornado, wind, heat, freeze, frost, weather, humidity, drought, flood, wildfire, el niño, enso, climate) produced **491 hits, all sports team/mascot names** (Golden Hurricane, Rainbow Warriors, Carolina Hurricanes, Miami Heat, Seattle Storm, Victor Snow…) and **0 non-sports, non-climate hits**. `/v1/search` for the same 22 keywords returned climate events only for weather/temperature/high temperature/heat; every other hit was sports, politics ("House seats" for "heat"), crypto ("How low will Bitcoin get" for "low temperature") or geopolitics ("Bab el-Mandeb" for "el nino").

Coverage caveats (UNVERIFIED beyond what was sampled): `politics` (2,000 of ≥2,000) and `culture` (1,000 of ≥1,000) were sampled at 4 and 2 pages respectively, not exhausted; the category list is not enumerable from the API (`categories` is a free string) so an undiscovered category name cannot be excluded — `weather`, `economics`, `entertainment`, `esports` each returned 200 with 0 markets.

## (C) New cities beyond the five

**None.** Description station text (3,623 markets dated ≥ 2026-04-29 except two early days): "Central Park (KNYC) in New York City", "San Francisco International Airport (KSFO)", "Miami International Airport (KMIA)", "Chicago Midway Airport (KMDW)", "Los Angeles International Airport (KLAX)" — identical to `sites.toml`. **Template drift:** the 120 markets dated 2026-04-22, 04-23, 04-29, 04-30 use an older template naming only the city ("recorded in New York City … as reported by the National Weather Service's Climatological Report (Daily)") with **no station and no ICAO**. All 3,743 name the NWS Climatological Report (Daily) as the source. Series taxonomy (277 series, one page): weather series are ids 31 `weather` (0 events) and 35–44 `weather-daily-{high,low}-{nyc,miami,chicago,los-angeles,san-francisco}`; no other weather-like series (the regex also caught `setka-cup-ukraine-*` and `r6` Rainbow Six via "rain" — sports, probed and confirmed sports).

## (D) Pagination / lifecycle facts (paths + params only)

- `/v1/markets?categories=climate&limit=500&offset={0,500,…,3500}` → 8 pages 500×7 + 243 = 3,743; envelope `{markets:[…]}`, **no total/cursor field**; short page terminates. `limit=1000&offset=0` → 500 returned (**server page cap = 500**). `…&includeHidden=true` → identical 3,743 (0 extra; `hidden=false` on all).
- `/v1/markets?limit=500&offset=N` (no category) → 2,499 markets, **all `sports`**, `status` = RESOLVED 2,498 + `MARKET_STATUS_CLOSED` 1; 0 climate. The default listing is not venue-wide.
- `/v1/markets?categories={crypto,geopolitics,science}` → 57 / 15 / 14 (single short pages); `politics` ≥ 2,000, `culture` ≥ 1,000 (sampled); `weather|economics|entertainment|esports` → 0.
- Lifecycle fields on climate: `status` ∈ {MARKET_STATUS_OPEN (60), MARKET_STATUS_RESOLVED (3,683)}; `closed` mirrors (false/true); `archived=false` and `hidden=false` on all; `active=false` only on the 60 markets of 2026-04-22/23 (all other resolved markets keep `active=true` — `active` is not a lifecycle marker). Open market stamps: `createdAt=startDate` = D-1 09:45Z (listing), `gameStartTime` = D 05:00Z, `endDate` = D+1 05:00Z; event `endDate` = D 23:59Z. Resolved: `outcomePrices` JSON-string, `bestBid/AskQuote` dropped.
- **Per-market fields drifted over time:** `minimumTradeQty` = `1` on all 1,440 markets dated 2026-04-22..06-13 and `0.01` on all 2,303 dated 2026-06-14..09-05 (no date has both); `orderPriceMinTickSize=0.01` and `feeCoefficient=0.06` on 3,743/3,743.
- Missing station-days in the archive (all 5 cities): 2026-04-24..04-28, 06-25..06-27, 07-08, 07-12, 08-28, 09-02 (12). LAX alone lacks 2026-08-06. `/v1/events?seriesId=35` → 124 events vs 125 NYC market-days (default event listing includes closed events; the 1-day discrepancy is recorded in the run analysis).
- `/v1/series?limit=500` → 277 (one page). Series objects carry `active, createdAt, id, image, recurrence, slug, subtitle, title, updatedAt` — no `closed/archived/category`; `archived=true` and `closed=true` filters returned the identical 277 (filter appears inert — UNVERIFIED, 1 session).
- `/v1/events?seriesId={36,38,40,42,44}` (daily-low series) → 0 events each, also with `archived=true&closed=true`.
- `/v1/search?query=weather&limit=50` → exactly 10 events (all climate, the 09-05 events); `status=closed` and `status=upcoming` returned the same 10 → search caps at 10 and `status` did not filter (UNVERIFIED beyond this session).
- Event object grammar: `temp-<city>high-<YYYY-MM-DD>` (= `ticker`), `seriesSlug=weather-daily-high-<city>`, tags `weather`, `daily`, `high`, `<city>`; `period='NS'`.

**Series-35 discrepancy resolved offline:** the one NYC market-day absent from `/v1/events?seriesId=35` is `temp-nychigh-2026-04-22` (its 6 markets are present in the climate walk); no event was returned that lacked markets. Event lifecycle tuples observed on series 35 `(closed, active, archived)`: `(false,true,false)`, `(true,true,false)`, `(true,false,false)`.

_Coordinator note: the 16,165-row per-market summary JSON (3.7 MB, sports/politics/culture slugs) was not committed; it stays in the session scratchpad. The analysis JSON here carries the aggregates the tables above were computed from._
