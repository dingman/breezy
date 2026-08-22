---
name: nws-cli-settlement
description: Load when implementing NWS CLI ingestion, settlement-grade record classification, correction detection, and provenance capture for Breezy's weather-market position settlement.
---

# NWS CLI Settlement Classification

**Why this skill exists**: pyIEM parses CLI text flawlessly, but it does NOT decide which record is settlement-grade. That judgment is Breezy's domain, and it is where a silent, money-losing correctness bug lives.

---

## THE CENTRAL TRAP — Two CLI Issuances Per Day

**Single largest settlement correctness risk.**

Every calendar day, api.weather.gov issues exactly **two** CLI products per location:

1. **PRELIMINARY (~4:44 PM local)** — Intraday snapshot. Headline reads "...THE <SITE> CLIMATE SUMMARY FOR <today>...". **Contains the line `VALID TODAY AS OF 0400 PM LOCAL TIME.`** DO NOT settle on this.
2. **FINAL (~2:27 AM local)** — Covers the PREVIOUS climate day. Headline reads "...THE <SITE> CLIMATE SUMMARY FOR <yesterday>...". **Does NOT contain the `VALID TODAY AS OF 0400 PM LOCAL TIME.` line.** ONLY this is settlement-grade.

**CRITICAL CORRECTION** (empirically verified 2026-08-22): The old rule claiming final reads "CLIMATE REPORT" vs preliminary reads "CLIMATE SUMMARY" is **false**. Both issuances use "CLIMATE SUMMARY" in the headline. The actual discriminator is **the presence or absence of `VALID TODAY AS OF 0400 PM LOCAL TIME.`** — a separate line that appears ONLY in the preliminary. Misreading a preliminary as final settles trades on a value NWS has not finalized.

**The bug**: ingestors who key on `issuanceTime` alone will treat a preliminary as final if the intraday issuanceTime happens to sort after a prior final. **Always extract `summary_date` from the headline text AND check for the `VALID TODAY AS OF …` line; never rely on issuanceTime metadata alone or on outdated REPORT/SUMMARY wording.**

Worked example:
```
Preliminary (DO NOT SETTLE):
  issuanceTime: 2026-08-22T20:44:00Z
  productText includes: "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 22..."
  productText includes: "VALID TODAY AS OF 0400 PM LOCAL TIME."
  summary_date: 2026-08-22 (today)
  
Final (ONLY THIS):
  issuanceTime: 2026-08-23T06:27:00Z
  productText includes: "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 22..."
  productText does NOT include "VALID TODAY AS OF 0400 PM LOCAL TIME."
  summary_date: 2026-08-22 (yesterday from final's perspective)
```

Both use "CLIMATE SUMMARY" in the headline. The preliminary contains `VALID TODAY AS OF 0400 PM LOCAL TIME.`; the final does not. The final's issuanceTime is LATER, summary_date references the PREVIOUS day. **Check for the `VALID TODAY AS OF …` line as the primary discriminator**, then use summary_date as the settlement anchor.

---

## Climate Day = Local STANDARD Time (Not UTC, Not DST)

**Climate day midnight→midnight is always STANDARD time for the location, never UTC, never the local DST-adjusted clock.**

For NYC (EST/EDT):
- A trading contract "NYC High Sep 1" refers to Sep 1 midnight→midnight EST (UTC-5), **regardless of whether Sep 1 happens to fall under EDT (UTC-4)**.
- Deriving the climate day from UTC is a settlement-correctness bug of the same class as the two-issuance trap.

Implication: parse the headline's date and the location's IANA timezone together, then CONVERT BACK to the standard time zone for that location to establish the climate day boundary. This prevents DST-boundary aliasing.

---

## Correction / Revision Detection

Corrections re-issue with:
- WMO BBB token in text line 2 set to `CCA`, `CCB`, etc. (rare but real — observed in CDUS41 KPHI 161019 CCA example)
- Title changed to include "CORRECTED" or headline suffix " CORRECTION"

**Critical limitation**: `api.weather.gov /products/{id}` endpoint returns only `id`, `wmoCollectiveId`, `issuingOffice`, `issuanceTime`, `productCode`, `productName`, `productText`. **The BBB field is not exposed.** Revision detection MUST be:

1. Re-poll `/products/types/CLI/locations/{loc}` to fetch all recent CLI products for the location.
2. For each new product, parse `summary_date` from `productText`. If it equals an already-settled date, flag as candidate revision.
3. Regex the raw `productText` for `CCA|CCB|CORRECTED|CORRECTION` patterns (case-insensitive).
4. Diff the parsed max/min against the stored value for that `(station, summary_date)` — if they differ, confirm it is a real revision.

**Frequency**: Corrections are RARE. In a 200-product sample, zero corrections were observed. They WILL NOT appear in casual testing but WILL matter in production when a max/min is corrected after initial settlement.

---

## Dedupe and Supersession

Every re-issue gets a **new UUID** from api.weather.gov, so the UUID itself is not a unique key.

**Dedupe key**: `(productCode, location, summary_date, sha256(raw_text))`. This ensures that:
- The same text issued twice at different times dedupes to one record.
- A corrected version (same summary_date, different max/min, different hash) does NOT dedupe and is stored as a new revision.

**Supersession write path** (rare, but required for correctness):
- Maintain a monotonic `revision_seq` per `(station, summary_date)` starting at 1.
- If a correction arrives after the `summary_date` was already marked as settled, increment the revision_seq and mark the prior record as superseded (e.g., a `is_superseded: true` flag).
- The settlement resolver then re-checks the LATEST revision for that summary_date, not the first one ingested.

---

## Four Distinct Identifier Spaces

A single weather site has FOUR names in different systems; conflating them is a silent bug.

| Space | Example | System | Usage |
|-------|---------|--------|-------|
| ICAO/ASOS | `KNYC` | /stations endpoint, METAR obs | Raw observations |
| CLI Location | `NYC` | /products/types/CLI/locations/{id} path | Settlement product lookup |
| AWIPS PIL | `CLINYC` | Line 3 of CLI product text | Structural validation |
| WFO/CWA | `OKX` (Office), `KOKX` (code) | issuingOffice field | Product issuer metadata |
| Lat/Lon | 40.7484, -73.9857 | /points endpoint | Forecast lookup |

**CLI Location vs AWIPS PIL** (NOT interchangeable):
- CLI location `NYC` appears in the api.weather.gov path `/products/types/CLI/locations/NYC`
- AWIPS PIL `CLINYC` appears on line 3 of the product text (e.g., `CLINYC`)
- Both are useful: PIL is a good structural allowlist check, but they are different identifiers in different positions

**Verified Polymarket weather cities** (complete list; all others are out-of-scope):
- NYC → KNYC (Central Park, ICAO) → NYC (CLI location) → KOKX (issuing office)
- San Francisco → KSFO → SFO → KMTR (issuing office)
- Miami → KMIA → MIA → KMFL (issuing office)
- Chicago → KMDW (Midway, NOT O'Hare KORD) → MDW → KLOT (issuing office)
- Los Angeles → KLAX → LAX → KLOX (issuing office)

**Critical fact**: KNYC is the Central Park climate site with continuous records since 1869. It is NOT an airport; it is distinct from KLGA (LaGuardia), KJFK (JFK), and KEWR (Newark). WBAN ID 94728 / GHCN ID USW00094728.

**Philadelphia does NOT trade on Polymarket.us** — `/stations/KPHI` does not exist in the api.weather.gov inventory. Never substitute or reference it.

---

## The Office Collision Hazard — Matching on issuingOffice is Worthless

**Empirically confirmed across all five Polymarket cities (2026-08-22)**: One WFO issues CLI products for multiple cities under an identical `issuingOffice` value:

- KOKX issues NYC + JFK + LGA + EWR (all NY/NJ area)
- KMTR issues SFO + OAK + SJC (Bay Area)
- KMFL issues MIA + FLL + APF (South Florida)
- KLOT issues MDW + ORD (Chicago area)
- KLOX issues LAX + BUR + LGB (LA basin)

**Consequence**: Matching a product to a city via `issuingOffice` alone is unreliable and will cause silent settlement errors.

**Only reliable guard**: Use a per-city **product-body header regex** matched verbatim against the raw product text. The headers observed live are:

- NYC: `...THE CENTRAL PARK NY CLIMATE SUMMARY...`
- San Francisco: `...THE SAN FRANCISCO AIRPORT CLIMATE SUMMARY...`
- Miami: `...THE MIAMI CLIMATE SUMMARY...`
- Chicago: `...THE CHICAGO-MIDWAY CLIMATE SUMMARY...`
- Los Angeles: `...THE LOS ANGELES INTL AIRPORT CA CLIMATE SUMMARY...`

**Critical parsing detail**: The observed LA header contains a double space (`LOS ANGELES  INTL`). Use `\s+` (one or more whitespace) in regex patterns, not `\s` (exactly one space) or literal spaces. A loose pattern like `THE\s+CHICAGO.*CLIMATE\s+SUMMARY` will match BOTH Midway and O'Hare products — do not use it.

**Recommended approach**: Maintain a structural allowlist of (city, ICAO, CLI location, header_regex, issuing_office) tuples per the registry at `src/breezy/registry/sites.toml` (single source of truth). Extract the CLI location and first 500 chars of product text, validate the header regex, then proceed.

---

## api.weather.gov Mechanics

- **No authentication** but **User-Agent header is mandatory** (missing or generic 403 → blocked)
- Rate limit undocumented ("generous"); 503s are intermittent → exponential backoff with jitter
- Retry after ~5 seconds on transient failure
- Formats via `Accept` header: `application/ld+json` for /products (required for settlement text)
- No URL version segment; changes gated by `Feature-Flags` request header + Service Change Notices
- Unknown query param → 400 (validate params before sending)
- Full HTTP caching: honor `Cache-Control`, `Last-Modified`, `ETag` headers to avoid redundant fetches

---

## Source Hierarchy: CLI vs METAR vs ACIS

| Source | Grade | QC | Timezone | Use Case |
|--------|-------|----|----|----------|
| **CLI** (text product) | Settlement-grade | Human, tenths→whole °F | Local STD | Sole settlement source |
| **METAR/ASOS** obs | Raw sensor truth | None; $ flag = maintenance | UTC | Reconciliation signal only |
| **ACIS** | Independent cross-check | RCC-ACIS curated | Local STD | Verify CLI matches |

**CLI is authoritative** for settlement. METAR (`/stations/{id}/observations`) is never settlement-grade; use it ONLY to detect venue-defined settlement-conflict branches (polymarket-us-integration owns the 08:00 ET / 11:00 ET conflict rule). 

**ACIS** (`https://data.rcc-acis.org/StnData?sid=NYC&sdate=...&elems=maxt,mint`) is an independent, unauthenticated JSON feed. Returns max/min for historical dates and `"M"` (missing) for future dates. ACIS independently reproduced a 2026-08-20 CLI's values exactly (84/63). Use ACIS to reconcile when a CLI value seems anomalous or to backfill historical data. No maintained Python package targets ACIS — hit the JSON endpoint directly.

**Gotcha**: `maxTemperatureLast24Hours` is frequently null on non-synoptic METAR observations. Do NOT build daily extremes from it.

---

## Use pyIEM — Do NOT Hand-Roll Parsing

**Pin exact versions in pyproject.toml**:
```toml
pyiem = "==1.27.0"  # CLI/F6 parsing, production-grade since 2024
metar = "==2.0.1"   # METAR decoding
pynws = "==2.1.0"   # Async client (forecasts/obs only, no text products)
```

**`pyiem.nws.products.cli`** (akrherz, battle-tested behind Iowa Environmental Mesonet) handles:
- CORRECTION regex (CCA/CCB, "CORRECTED", " CORRECTION" suffix)
- M/MM (missing), T (trace), unit conversion (°F rounding)
- Multi-station CLIs (section splitting)
- AM/PM time-column format drift across WFOs
- Whitespace-delimited fixed-width column parsing per office

Similarly, `pyiem.nws.products.cf6` parses the F6 form (monthly/daily climate table). **Do not reimplement this.**

**CRITICAL: pyIEM Parser Architecture** — `pyiem.parser()` opens a **live PostgreSQL connection** by default on the standard path. For settlement-critical parsing:
1. Construct the parser **offline** (pass `dbname=None` or an in-memory fallback) to avoid blocking the trading event loop.
2. Run CLI parsing **behind a structural allowlist** (city/ICAO/header regex tuple from the registry).
3. Wrap the parser in a **killable executor with a timeout** (10–60 seconds depending on text size). ReDoS in regex-heavy fixed-width parsing can stall the asyncio thread indefinitely, orphaning the trading loop. A timeout-wrapped subprocess or thread pool prevents this.
4. Catch and log timeout/parsing exceptions separately from business logic; never re-raise to the trading context.

**Libraries to AVOID** (stale/unmaintained): nwswx, nwsapy, noaa-sdk.

**Gotcha**: Even with pyIEM, validate parser output against physical sanity bounds before trusting it as settlement input. Defense against malformed upstream text AND parser bugs.

Bounds are **max ≤ 140°F, min ≥ -100°F, tmin ≤ tavg ≤ tmax** (equality accepted — CLI publishes whole degrees, so a fog-locked SFO day legitimately rounds all three to the same value), plus a **diurnal range ≤ 130°F**.

**140, not 130.** An earlier revision of this file said 130°F, which is *below* the WMO-recognised record of 134°F (Death Valley, 1913) — that is a bound on "unusual", not on "impossible", and it would reject a record-breaking day. Get the asymmetry right: a bound that is too wide lets one absurd value through into a gate that has several other guards, while a bound that is too tight takes the bot offline **precisely when a record-breaking day makes the market most interesting**. Err wide. Our five sites top out near 110°F, so 140 leaves ~30°F of headroom over anything they can produce.

**The diurnal-range bound is not redundant with the per-field envelope**, and this is the load-bearing argument for keeping it: the envelope alone permits a 240°F span (140 paired with -100) because it never inspects the two values *together*. A column shift that pairs a real MAXIMUM with another row's MINIMUM yields two individually-plausible numbers and one impossible pair. Calibrate it from the world record 100°F swing (Browning MT, 1916), never from our sites' observed ~40-45°F ranges — otherwise it becomes the constraint that halts a record day.

---

## Parsing Hazards to Expect

Even with pyIEM, be prepared for:
- Fixed-width whitespace-delimited columns that shift between WFOs
- M/MM (missing), T (trace), MS (missing at time), MB (missing at midnight)
- Time column formats: "259 PM" vs "4:49 PM" vs "259" (military) across different offices
- Multi-station CLIs in one product (section splitting required)
- Blank continuation lines (multi-year records wrapping)
- "CLIMATE NORMAL PERIOD 1991 TO 2020" headers with or without colons
- Trailing spaces and inconsistent delimiters

---

## Required Provenance Per Datum

Store ALL of these with every ingested CLI record (immutably, preferably raw_text separately):

- `product_uuid` (assigned by api.weather.gov)
- `productCode` (always "CLI")
- `issuingOffice` (e.g., "KOKX")
- `wmoCollectiveId` (e.g., "CDUS41")
- `issuanceTime` (ISO 8601)
- `awips_pil` (text line 3, e.g., "CLINYC")
- `wmo_bbb_token` (text line 2, e.g., "CCA" if correction)
- `retrieved_at` (timestamp when fetched)
- `raw_text` (verbatim, immutable)
- `sha256_raw_text` (hex digest; verify before any re-read)
- `parsed_summary_date` (date extracted from headline)
- `parsed_station_id` (CLI location, e.g., "NYC")
- `is_final_flag` (boolean: does headline indicate this is the final/yesterday report?)
- `correction_flag` (boolean: detected via regex or diff)
- `revision_seq` (monotonic per station+summary_date, starts at 1)
- `parser_version` (pyiem version used)
- `response_last_modified` (from HTTP header, if present)
- `response_etag` (from HTTP header, if present)

Store raw_text IMMUTABLY — the api.weather.gov exposes no archive guarantee. The Iowa Environmental Mesonet AFOS archive is the practical fallback if a product vanishes from the live API.

**Before using any datum for settlement**, verify `sha256(raw_text)` matches the stored digest. Defense against accidental mutation or replay.

---

## Operational Hazards

- **Late or absent final CLI** (staffing constraints, holidays, federal shutdowns). The 2025 government shutdown ran Oct 1 — Nov 12 (43 days) and limited some data feeds.
- **Intraday CLI mistaken for final** (the two-issuance trap again).
- **API timeouts or 403/503** (missing User-Agent → 403; overload → 503; bad params → 400).
- **Climate day boundary edge cases** (DST transitions, time-zone ambiguity). Use the IANA timezone + standard time conversion to avoid it.

---

## Station Substitution is Prohibited

**Never substitute a nearby station for the settlement station under any circumstance**, including when the settlement product is missing or arrives late:

- NYC (KNYC Central Park) ≠ JFK (KJFK) ≠ LaGuardia (KLGA) ≠ Newark (KEWR)
- Chicago Midway (KMDW) ≠ O'Hare (KORD)
- Los Angeles (KLAX) ≠ Burbank (KBUR) ≠ Long Beach (KLGB)
- San Francisco (KSFO) ≠ Oakland (KOAK) ≠ San Jose (KSJC)
- Miami (KMIA) ≠ Fort Lauderdale (KFLL) ≠ Opa Locka (KOPF)

These sites have independent CLI products with independent max/min values. A late or missing CLI does NOT justify reaching for a substitute. If a settlement product is missing, escalate to the trading ops team and venue-integration; never auto-substitute.

---

## Station Registry — Single Source of Truth

**Authoritative binding of (venue, city) to station identifiers lives in `src/breezy/registry/sites.toml`** (machine-readable TOML).

The station/office table in this skill (earlier in Four Distinct Identifier Spaces) is illustrative and secondary. If a discrepancy arises, **always consult the registry file in the codebase**. The registry is the enforced configuration; this skill is reference documentation.

Never hardcode station identifiers (ICAO, CLI location, AWIPS PIL, issuing office, timezone) in settlement logic. Always fetch from the registry at runtime.

---

## Boundaries — What This Skill Does NOT Own

- **Does NOT re-implement parsing**: pyIEM owns it. Call pyIEM, validate output, move on.
- **Does NOT own venue settlement timing**: polymarket-us-integration is the authoritative owner. That skill defines 08:00 ET settlement, 11:00 ET conflict-branch delay, 7-day fallback, and the station→market mapping. This skill only supplies the best-available CLI data; it does NOT forward-infer a resolution or make trading decisions.
- **Does NOT include trading logic, strategy, edge, or sizing.**
- **Does NOT make venue-specific settlement calls.** It classifies which CLI is settlement-ready; the venue decides when and how to use it.

---

## Quick Reference: Checklist for Settlement-Readiness

Before marking a CLI record as ready for settlement:

- [ ] Extract `summary_date` from headline text (not from `issuanceTime`)
- [ ] Confirm product is final by checking for absence of `VALID TODAY AS OF 0400 PM LOCAL TIME.` line (preliminary's discriminator)
- [ ] Validate station via product-body header regex against registered pattern (NOT `issuingOffice` alone)
- [ ] Verify local STANDARD time for climate day (not UTC, not DST clock)
- [ ] Check for correction patterns (CCA/CCB/CORRECTED/CORRECTION) in raw text
- [ ] Re-poll `/products/types/CLI/locations/{loc}` for candidate supersessions if already settled
- [ ] Dedupe on `(productCode, location, summary_date, hash)`, never on UUID
- [ ] Use monotonic `revision_seq` if a correction lands after settlement
- [ ] Validate parsed max/min/avg against sanity bounds (max ≤ 140°F, min ≥ -100°F, tmin ≤ tavg ≤ tmax, diurnal range ≤ 130°F) — see the bounds note above for why 140 and not 130
- [ ] Store all 16 provenance fields including raw_text + sha256
- [ ] Cross-check via ACIS if anomalous
- [ ] Consult `src/breezy/registry/sites.toml` (not this skill's table) for station configuration
- [ ] Ref polymarket-us-integration for settlement timing and station mapping; do not infer resolution ahead of venue
