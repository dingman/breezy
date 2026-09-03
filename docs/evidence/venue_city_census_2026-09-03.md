# Polymarket.us city census — what the venue lists BEFORE the recorder's city filter

Observed 2026-09-03 00:05–00:12 UTC at repo `9284646`. `provisional: true` (one session, one date; needs a second-date reproduction + python-reviewer / prediction-market-reviewer sign-off).

## Method
- Official `polymarket_us` 0.1.2 SDK, `PolymarketUS()` with NO credentials → unauthenticated public gateway `GET /v1/markets` only. No auth header, no private path, no write verb. Paced ≥1 s/request with jitter, 3-failure circuit breaker, hard page cap; ~55 requests total, zero 429s, zero non-200s.
- Pagination is `limit`+`offset` (no cursor); `limit=500` honoured. Walks: (a) `categories=climate&active=true`, (b) `categories=climate` unfiltered, (c) the recorder's exact query `categories=climate&active=true&closed=false&archived=false`, (d) `active=true&closed=false&archived=false` with no category (capped at 24 pages = 12 000 rows, TRUNCATED), (e) `active=true` no category (2 499 rows, all resolved sports).
- Grouping: `question` matched against provider.py:87 grammar `^(Highest|Lowest) temperature in <city> on `; slug matched against `tc-temp-<city><high|low>-<YYYY-MM-DD>-<bounds>`. Script: scratchpad `census_probe.py` / `census_probe2.py` (not committed).

## (1) Weather markets — currently OPEN (the recorder's view, before the city filter)

| city (question) | slug prefix | measure | climate day(s) | rungs | tick | minQty |
|---|---|---|---|---|---|---|
| NYC | `tc-temp-nychigh-` | Highest only | 2026-09-03 | `lt83f, gte83lt84f, gte85lt86f, gte87lt88f, gte89lt90f, gte91f` | 0.01 | 0.01 |
| San Francisco | `tc-temp-sfohigh-` | Highest only | 2026-09-03 | `lt66f … gte74f` (6) | 0.01 | 0.01 |
| Miami | `tc-temp-miahigh-` | Highest only | 2026-09-03 | `lt87f … gte95f` (6) | 0.01 | 0.01 |
| Chicago | `tc-temp-mdwhigh-` | Highest only | 2026-09-03 | `lt88f … gte96f` (6) | 0.01 | 0.01 |
| Los Angeles | `tc-temp-laxhigh-` | Highest only | 2026-09-03 | `lt72f … gte80f` (6) | 0.01 | 0.01 |
| **total** | | | **1 climate day** | **30 = 5 × 1 × 6** | | |

- **The city filter is a no-op today: the venue lists exactly the five configured cities and nothing else.** `_weather_market_payloads` would RAISE (not skip) on an unregistered city, so a sixth city could never have been silently dropped — `discovered 30 total` is the whole open weather universe.
- Only ONE climate day is open at 00:05 UTC (2026-09-03); on 2026-08-30 the log saw two days (60). The next day's ladder is evidently not listed until later in the UTC day. `active=true` alone does NOT narrow to open — it returned 3 593 resolved + 30 open; `closed=false` is the discriminator.
- Rung grammar on all 5: one `lt<N>f` tail, four 1 °F-wide interiors `gte<N>lt<N+1>f` stepping by 2 °F (so labelled bounds are non-contiguous), one `gte<N>f` tail. `Lowest temperature` / `-low-` slugs: **zero** in 3 683 markets of history.

## (1b) Full climate history (walk b, 3 683 markets, 123 station-days 2026-04-22 → 2026-09-03)
- Same 5 cities on every day; never a sixth; never a `low` market. 30 markets/station-day except 2026-07-09 (29) and 2026-08-06 (24: LAX absent). Days absent from the archive: 06-25, 06-26, 06-27, 07-08, 07-12, 08-28, 09-02.
- `minimumTradeQty` was **`1` on every market through climate day 2026-06-13 and `0.01` from 2026-06-14 onward** (all 5 cities flipped on the same day; `orderPriceMinTickSize` 0.01 throughout). Per-market fields DO drift over time — re-read them per session, never pin them.
- `active=true` excludes the 04-22…04-28 markets (3 623 vs 3 683): `active` is a listing flag, not an open/closed flag.

## (2) Non-weather markets — OPEN (walk d, first 12 000 rows, truncated at the page cap)
| sports | politics | culture | macro | finance | crypto | technology | geopolitics | science | climate |
|---|---|---|---|---|---|---|---|---|---|
| 8 808 | 2 424 | 524 | 75 | 62 | 49 | 41 | 9 | 8 | **0** |

`tc-*` slugs in the unfiltered listing: 0 — reconfirms (third date) that climate is reachable ONLY via `categories=climate`. Open non-weather universe is ≥12 000; the exact total was not walked (rate-limit budget).

## (3)/(4) Additional weather cities
| city | slug prefix | high/low | settling ICAO → CLI PIL | IEM ASOS 5-min | CLI readers need |
|---|---|---|---|---|---|
| *(none — venue lists no city beyond NYC/SFO/MIA/MDW/LAX)* | — | — | — | — | — |

Mechanics, for when one appears: `sites.toml` stores `icao`, `cli_location` (PIL = `CLI` + `cli_location`), `issuing_office`, `venue_city_token`, `body_header_regex` as explicit values (never derived). `settlement_alignment_study.asos_url` sends `station=IEM_ASOS_IDS[site.icao]` to the IEM 5-minute ASOS endpoint — that map is HARDCODED (`settlement_alignment_study.py:65`) and `pmr_climatology_study` imports `load_sites` from it, so a new city needs a registry row **plus** an `IEM_ASOS_IDS` entry and a verified body-header regex; a registry row alone is NOT sufficient. No IEM network check was made (no candidate station to check).

## Effect on the M_B sample clock
None available from the venue side. With the open universe fixed at 5 cities × 1 ladder/day, the trial denominator stays at 5 station-days/day and the ~3 taken trials/day rate in `grok_mb_kill_amendment_2026-09-02.md` §Clock is not liftable by adding cities: kill n≥60 stays ~20 climate days (~2026-09-22) and survive n≥150 ~50 days (~2026-10-21). The only levers that remain are the taken/covered ratio (1/4 on 09-01) and afternoon coverage — both on Breezy's side. If the venue ever adds a `-low-` measure or a sixth city, that is a 20–100 % denominator lift and would show up first as a `VenuePayloadError` from `_weather_market_payloads` naming the new city.
