# Polymarket.us Weather Slug Threshold Semantics — Resolved

**Date:** 2026-08-25
**Author:** nautilus-adapter-builder (investigation; no code changed)
**Verdict:** **INCLUSIVE PROVEN.** The literal strict-`lt` reading is REFUTED.

---

## 1. The Question

Polymarket.us weather market slugs encode buckets as `gte72lt73f`. Read literally as a
strict inequality, `lt73` excludes 73 and the bucket covers only the single value 72.
The venue's own `title` / `description` for the same market reads inclusively
("72° to 73°"). Prior corpus analysis found a total split: all 225 single-sided markets
corroborate their prose, all 455 two-token range markets contradict it.

If Breezy adopts the strict reading it assigns zero probability to an outcome that
actually settles YES, mispricing the entire ladder on 67% of the corpus.

## 2. Market Facts (read from committed JSON, not assumed)

Source: `docs/evidence/venue/polymarket_us/raw/market_closed_15806_by_id.json`

| Field | Value |
|---|---|
| `id` | `15806` |
| `slug` | `tc-temp-nychigh-2026-04-23-gte72lt73f` |
| `question` | "Highest temperature in NYC on April 23, 2026?" |
| `title` / `titleShort` | `72° to 73°` |
| `description` | "...between 72°F and 73°F ... as reported by the National Weather Service's Climatological Report (Daily)..." |
| `status` | `MARKET_STATUS_RESOLVED` |
| `outcomes` | `["Yes","No"]` |
| `outcomePrices` | `["1","0"]` → **resolved YES** |
| Station implied | NYC (registry: `polymarket_us`/`NYC` → KNYC Central Park, CLI location `NYC`, WFO KOKX) |
| Contract date | 2026-04-23 |

The market's own description names the CLI (Daily Climatological Report) as the
settlement source, which is the record class the `nws-cli-settlement` skill governs.

## 3. The NWS Observation

### 3.1 Availability of the live API

`api.weather.gov` CLI retention is a rolling ~7 days. Probed 2026-08-25T17:43Z:

- `GET https://api.weather.gov/products/types/CLI/locations/NYC` → oldest `issuanceTime`
  present was `2026-08-18T20:33:00+00:00`. 14 products total.
- `GET https://api.weather.gov/products?type=CLI&location=NYC&start=2026-04-23T00:00:00Z&end=2026-04-25T00:00:00Z`
  → HTTP 200, `"@graph": []` (empty).

The April product is **not** retrievable from the live API. No local capture exists
either: Breezy's ingestion began 2026-08 (`docs/evidence/ingestion/LIVE_RUN_2026-08-24.md`,
`PHASE1_LIVE_VALIDATION.md`) and no ParquetDataCatalog holds 2026-04 data.

### 3.2 Archive fallback (skill-sanctioned)

`nws-cli-settlement` names the **Iowa Environmental Mesonet AFOS archive** as
"the practical fallback if a product vanishes from the live API", and **ACIS**
(`data.rcc-acis.org`) as the sanctioned independent historical cross-check. Both are
free, public, unauthenticated, read-only, and unrelated to the trading venue. No
polymarket.us host was contacted.

**Product discovery** — `GET https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil=CLINYC&date=2026-04-24`
retrieved 2026-08-25T17:43:05Z. Exactly two CLINYC products that day:

| product_id | entered | Role |
|---|---|---|
| `202604240617-KOKX-CDUS41-CLINYC` | 2026-04-24T06:17:00Z | **FINAL** for summary_date 2026-04-23 |
| `202604242038-KOKX-CDUS41-CLINYC` | 2026-04-24T20:38:00Z | preliminary for 2026-04-24 |

This matches the skill's two-issuance-per-day pattern exactly (~02:17 AM local final,
~04:38 PM local preliminary).

**Raw text** — `GET https://mesonet.agron.iastate.edu/api/1/nwstext/202604240617-KOKX-CDUS41-CLINYC`
retrieved 2026-08-25T17:43:16Z.

- Archived verbatim at `docs/evidence/venue/polymarket_us/raw/nws/CLINYC_202604240617-KOKX-CDUS41-CLINYC.txt`
- `sha256 = d8909a8c10e56a265efd584491f640c43c417ed5ad43f38b48e9dd2d409e7249`
  (recorded in `raw/nws/SHA256SUMS.txt`)

### 3.3 RAW TEXT (verbatim excerpt — the auditable reading)

```
207
CDUS41 KOKX 240617
CLINYC

CLIMATE REPORT
NATIONAL WEATHER SERVICE NEW YORK, NY
217 AM EDT FRI APR 24 2026

...................................

...THE CENTRAL PARK NY CLIMATE SUMMARY FOR APRIL 23 2026...

CLIMATE NORMAL PERIOD 1991 TO 2020
CLIMATE RECORD PERIOD 1869 TO 2026


WEATHER ITEM   OBSERVED TIME   RECORD YEAR NORMAL DEPARTURE LAST
                VALUE   (LST)  VALUE       VALUE  FROM      YEAR
                                                  NORMAL
...................................................................
TEMPERATURE (F)
 YESTERDAY
  MAXIMUM         73    257 PM  86    2007  65      8       76
  MINIMUM         45    535 AM  29    1872  48     -3       54
  AVERAGE         59                        56      3       65
```

### 3.4 Settlement-grade classification and parsed value

Parsed with Breezy's **production** parser — `breezy.normalize.cli_parse.parse_cli_product`,
with the station guard taken from `breezy.registry.sites.default_registry()`
(`polymarket_us`/`NYC` → `body_header_regex = ^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b`).
Nothing was hand-parsed and no source or test file was modified.

```
ParsedCliProduct(
    summary_date=datetime.date(2026, 4, 23),
    station_header_line='...THE CENTRAL PARK NY CLIMATE SUMMARY FOR APRIL 23 2026...',
    tmax=TemperatureReadingF(value_f=73, sentinel='NONE', is_record=False),
    tmin=TemperatureReadingF(value_f=45, sentinel='NONE', is_record=False),
    tavg=TemperatureReadingF(value_f=59, sentinel='NONE', is_record=False),
    awips_pil='CLINYC',
    wmo_bbb=None,
)
```

Settlement-grade checks, per the skill's checklist:

- [x] `summary_date` = **2026-04-23**, extracted from the headline, not from `issuanceTime`.
- [x] **FINAL, not preliminary** — the string `VALID TODAY AS OF 0400 PM LOCAL TIME.` is
      ABSENT from the product (verified programmatically). The observed sub-block is
      labelled `YESTERDAY`, which the parser anchors on.
- [x] **Station bound by body-header regex**, not `issuingOffice` — the KOKX office also
      issues JFK/LGA/EWR; the header proves Central Park.
- [x] AWIPS PIL = `CLINYC`, matching `CLI` + registry `cli_location`.
- [x] **No correction** — `wmo_bbb=None`; regex scan for `CCA|CCB|CORRECTED|CORRECTION`
      returned zero matches. The AFOS archive for 2026-04-24/25/26 lists only the normal
      two products per day, so no later revision supersedes this reading.
- [x] **No record qualifier** — `is_record=False`, `sentinel='NONE'`. The value is a plain
      integer `73`, not `73R`. (This is the trap recent commits fixed; it does not apply here.)
- [x] Physical sanity bounds passed (the parser raises `CliSanityError` otherwise);
      tmin 45 ≤ tavg 59 ≤ tmax 73, diurnal range 28°F.

**Transport-envelope note (full disclosure).** The IEM archive frames the product with the
WMO sequence number (`207 `) on line 1, where `api.weather.gov` emits a blank leader plus a
`000` transmission indicator. Breezy's structural allowlist asserts the api.weather.gov
framing, so the IEM leader line was replaced with `"" / "000"` before parsing. Everything
from the WMO abbreviated heading (`CDUS41 KOKX 240617`) onward was passed through byte-identical
— verified by assertion. This is a transport transcode of the envelope only; no character of
the climate body was altered. The sha256 above is of the **unmodified IEM bytes**.

### 3.5 Independent cross-check (ACIS)

`GET https://data.rcc-acis.org/StnData?sid=NYC&sdate=2026-04-21&edate=2026-04-25&elems=maxt,mint`
retrieved 2026-08-25T17:43:07Z. Archived at `raw/nws/acis_NYC_2026-04-21_2026-04-25.json`
(`sha256 = 95a79cc0d4a73cf458c52863b8747d91b6b6d0f56657b8e137116c99cec34c88`).

Station meta confirms identity: `"name": "NY CITY CENTRAL PARK"`, sids include `KNYC`,
`94728`, `USW00094728`. Data:

```
["2026-04-23","73","45"]
```

ACIS independently reproduces the CLI's 73/45 exactly.

## 4. Verdict — INCLUSIVE PROVEN

The decisive test as framed: if the official NWS observed daily high for KNYC on
2026-04-23 was exactly **73°F**, the venue settled inclusively and the literal `lt`
reading is refuted.

**It was exactly 73°F.**

Market `tc-temp-nychigh-2026-04-23-gte72lt73f` **resolved YES** (`outcomePrices` `["1","0"]`).

- Under the **literal/strict** reading, the bucket is `72 ≤ x < 73` = {72}. An observed
  high of 73 falls OUTSIDE it, and the market would have had to resolve **NO**. It did not.
  **The strict reading is refuted outright.**
- Under the **inclusive** reading, the bucket is `72 ≤ x ≤ 73`, 73 is inside, and YES is
  correct. Consistent.

### 4.1 Second, independent structural proof (from the committed corpus alone)

The full 2026-04-23 NYC ladder, extracted from
`docs/evidence/venue/polymarket_us/raw/events_seriesId_35.json`:

| id | slug | title | outcomePrices |
|---|---|---|---|
| 15798 | `tc-temp-nychigh-2026-04-23-lt66f` | 65° or below | `["0","1"]` NO |
| 15800 | `tc-temp-nychigh-2026-04-23-gte66lt67f` | 66° to 67° | `["0","1"]` NO |
| 15804 | `tc-temp-nychigh-2026-04-23-gte68lt69f` | 68° to 69° | `["0","1"]` NO |
| 15802 | `tc-temp-nychigh-2026-04-23-gte70lt71f` | 70° to 71° | `["0","1"]` NO |
| 15806 | `tc-temp-nychigh-2026-04-23-gte72lt73f` | 72° to 73° | `["1","0"]` **YES** |
| 15808 | `tc-temp-nychigh-2026-04-23-gte74f` | 74° or above | `["0","1"]` NO |

**The ladder steps by 2°F, not 1°F.** The lower bounds run 66, 68, 70, 72, 74. Under the
literal reading the buckets would be {66}, {68}, {70}, {72} — and 67, 69, 71, 73 would be
covered by *no market at all*, so a day topping out at 73 would resolve the entire ladder
NO. Under the inclusive reading the buckets are `≤65`, `[66,67]`, `[68,69]`, `[70,71]`,
`[72,73]`, `≥74` — contiguous, mutually exclusive, collectively exhaustive, with no gaps.

This is decisive on its own and needs no external data: the 2°F stride is only coherent
under inclusive upper bounds. The NWS observation of 73°F then confirms it empirically by
landing on an upper bound and settling YES — the single most discriminating value available.

### 4.2 Reading rule established

For two-token weather slugs `gte{A}lt{B}f`, the settling predicate is:

```
A <= observed <= B        (INCLUSIVE on both bounds)
```

The `lt` token in the slug is **venue naming, not the settlement predicate**. The
authoritative statement of the bucket is the market's `title` / `description` prose
("A° to B°"), which the slug abbreviates misleadingly.

Single-sided slugs are unaffected and keep their literal reading (`lt66f` = `≤65`,
`gte74f` = `≥74`), which is exactly the corroboration pattern the corpus analysis found.

## 5. Scope and Constraints Honoured

- No change to `symbology.py`, its refusal gate, or any test. The gate remains closed;
  lifting it is a separate, reviewed change informed by this evidence.
- No settlement logic built.
- No `src/` or `tests/` modification. Only this document and `raw/nws/` evidence files added.
- No polymarket.us host contacted. Network use limited to `api.weather.gov`,
  `mesonet.agron.iastate.edu`, and `data.rcc-acis.org` — all public, unauthenticated,
  read-only, with a specific non-generic User-Agent (`BreezyEvidenceProbe/1.0 (jon@gopoint.com)`).
- No observation fabricated. Every number above traces to an archived, digested raw response.

## 6. Recommended Follow-up (not done here)

1. Route this finding to `polymarket-us-integration` skill maintenance: record the
   inclusive-bounds reading rule as a venue fact with these citations.
2. Have `prediction-market-reviewer` and `python-reviewer` independently review this
   verdict before the symbology refusal gate is lifted. **This finding is not self-approved.**
3. When the gate is lifted, add a contract test asserting `gte72lt73f` admits 73, pinned to
   market 15806 as the regression anchor.
4. Optional hardening: the 2°F ladder stride is itself a checkable invariant — a ladder
   whose buckets do not tile the integers without gap or overlap is a symbology defect and
   could fail loudly at parse time.
