# Kalshi daily temperature series — public enumeration, 2026-09-04

Status: MEASURED (public API, unauthenticated, GET only, 103 requests, ~4.5 rps, User-Agent header only). Closes KALSHI_INTEGRATION_PLAN_2026-09-03 §1.5 (series enumeration — was MISSING). Feeds `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` §Stations.

## Method
- Base URL, pacing and backoff reused from `scripts/analysis/k1_kalshi_prior.py:213,865-940`.
- `GET /trade-api/v2/series?category=Climate%20and%20Weather` → 369 series, unpaged (no cursor). Raw: `raw/series_climate.json` (sha256 in `raw/enumeration_2026-09-04.sha256`).
- For each of the 102 daily `KXHIGH*`/`KXLOW*` series: `GET /trade-api/v2/events?series_ticker=<T>&status=open&limit=200&with_nested_markets=true`. `rules_primary` exists only on market objects, not on `/series`. Raw (1.9 MB, not committed): scratchpad `kalshi_enum/open_events.json`, sha256 `64091448…7128` recorded in the sidecar.

## Result
- All 102 daily series: `category="Climate and Weather"`, `fee_type="quadratic"`, `fee_multiplier=1`.
- **24 US cities have an open daily event today, each with BOTH a high and a low series (48 series, 2 open events each).** Station is QUOTED from `rules_primary`, never inferred.
- All five known cities present: NYC `KXHIGHNY`/CLINYC, MIA `KXHIGHMIA`/CLIMIA, Chicago `KXHIGHCHI`/**CLIMDW**, LAX `KXHIGHLAX`/CLILAX, SFO `KXHIGHTSFO`/CLISFO. → **19 candidate new stations** beyond the current five.

| CLI station (quoted) | HIGH | LOW | settlement_sources |
|---|---|---|---|
| Atlanta (CLIATL) | KXHIGHTATL | KXLOWTATL | The Weather Company |
| Austin (CLIAUS) | KXHIGHAUS | KXLOWTAUS | The Weather Company |
| Boston (CLIBOS) | KXHIGHTBOS | KXLOWTBOS | The Weather Company |
| Chicago (CLIMDW) | KXHIGHCHI | KXLOWTCHI | The Weather Company |
| Dallas (CLIDFW) | KXHIGHTDAL | KXLOWTDAL | The Weather Company |
| Denver (CLIDEN) | KXHIGHDEN | KXLOWTDEN | The Weather Company |
| Houston (CLIHOU) | KXHIGHTHOU | KXLOWTHOU | The Weather Company |
| Las Vegas (CLILAS) | KXHIGHTLV | KXLOWTLV | The Weather Company |
| Los Angeles (CLILAX) | KXHIGHLAX | KXLOWTLAX | The Weather Company |
| Louisville (CLISDF) | KXHIGHTSDF | KXLOWTSDF | The Weather Company |
| Miami (CLIMIA) | KXHIGHMIA | KXLOWTMIA | The Weather Company |
| Minneapolis (CLIMSP) | KXHIGHTMIN | KXLOWTMIN | The Weather Company |
| New Orleans (CLIMSY) | KXHIGHTNOLA | KXLOWTNOLA | The Weather Company |
| New York City (CLINYC) | KXHIGHNY | KXLOWTNYC | The Weather Company |
| Newark (CLIEWR) | KXHIGHTEWR | KXLOWTEWR | The Weather Company |
| Oklahoma City (CLIOKC) | KXHIGHTOKC | KXLOWTOKC | The Weather Company |
| Philadelphia (CLIPHL) | KXHIGHPHIL | KXLOWTPHIL | The Weather Company |
| Phoenix (CLIPHX) | KXHIGHTPHX | KXLOWTPHX | The Weather Company |
| San Antonio (CLISAT) | KXHIGHTSATX | KXLOWTSATX | The Weather Company |
| San Diego (CLISAN) | KXHIGHTSAN | KXLOWTSAN | The Weather Company |
| San Francisco (CLISFO) | KXHIGHTSFO | KXLOWTSFO | The Weather Company |
| Seattle (CLISEA) | KXHIGHTSEA | KXLOWTSEA | The Weather Company |
| Trenton (CLITTN) | KXHIGHTTTN | KXLOWTTTN | The Weather Company |
| Washington DC (CLIDCA) | KXHIGHTDC | KXLOWTDC | The Weather Company |

Rules template (verbatim, KXHIGHNY): "If the maximum temperature recorded at New York City (CLINYC) for Sep 4, 2026, is less than 82° fahrenheit according to The Weather Company, then the market resolves to Yes."

## Flags
- `settlement_sources` says "The Weather Company" while the rules quote an NWS CLI product id. The K1 study already treats the post-`ERA_BOUNDARY` era this way; the settlement-truth reconciliation (CLI final vs venue settlement) must be re-measured per new station before any is added to the registry — do not inherit the four-station divergence rate.
- Title/rules drift: `KXHIGHTSDF` title says "SATX", rules say Louisville (CLISDF); `KXLOWTMIN` title "Minnesota", rules Minneapolis (CLIMSP); `KXLOWTSDF` title "SDX". Rules are authoritative; a symbology test must pin this.
- 54 daily series returned zero open events: international (`KXHIGHT{EGLL,LFPG,RJTT,ZBAA,…}`) and legacy US duplicates (`KXLOWNY`, `KXLOWNYC`, `KXLOWCHI`, `KXHIGHHOU`, `KXHIGHOU`, `KXHIGHUS`). Dormant.
- Non-`KX` legacy duplicates (`HIGHNY`, `HIGHCHI`, `HIGHMIA`, `HIGHAUS`) carry `settlement_sources = National Weather Service` — the pre-2023 era.
- Excluded by design: hourly directional (`KXTEMP*H`, `KXHIGHNYD`), `custom`/`one_off`/`monthly` frequency series, and `KXCITIESWEATHER` (multi-city daily).

## Next measurement
5-minute ASOS cadence per candidate station (the `config.py:16-29` exclusion rule) — see `docs/evidence/kalshi_station_cadence_2026-09-04.md` when landed.
