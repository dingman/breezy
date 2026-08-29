# Forecast Endpoint Probe Evidence - 2026-08-29

## EVIDENCE ONLY - NEVER INGEST

These captures are **EVIDENCE ONLY**. They must **NEVER** be ingested into the
production forecast catalog under any circumstance. Backfilling these payloads
under a plausible retrieval timestamp would be backdating and would violate the
point-in-time forecast design this probe exists to protect.

Generated at UTC: 2026-08-29T03:51:17Z

Scope: live, read-only GET probe against `api.weather.gov` for Increment I-0 of
`docs/plans/FORECAST_INGESTION_PLAN.md`.

Payload directory:
`docs/evidence/forecast_endpoint_probe_2026-08-29_payloads/`

Transport headers matched `src/breezy/ingest/http.py`:

- `User-Agent`: sourced from `BREEZY_USER_AGENT` in
  `/home/jon/.config/breezy/breezy.env`; value intentionally not copied into
  this repo evidence document because it contains the operator contact address.
- `Accept: application/ld+json`
- `Accept-Encoding: identity`
- redirects not followed in the clean manifest.

## Safety Deviation And Request Accounting

The approved cap was approximately 20 HTTP requests. The conservative actual
spend was **23 requests to `api.weather.gov`**.

Why: the first attempted command incorrectly used `curl --location-trusted false`.
Curl interprets `--location-trusted` as enabling redirect following and treated
`false` as an extra URL. Five exact `/points/{lat},{lon}` invocations were
started before the command was stopped. Terminal output showed canonical rounded
`/points` 200 bodies, so this evidence counts that discarded attempt as **10
api.weather.gov requests**: five exact `/points` requests plus five followed
canonical `/points` requests. The discarded body captures were unusable and were
not kept. No 403 or 429 was observed.

The clean manifest then recorded **13 more** requests:

- `request_manifest.tsv` - clean request list, timestamps, URLs, status, sizes.
- `probe_status.tsv` - conservative count: 10 discarded + 13 clean = 23.
- `discarded_attempt_note.txt` - note describing the discarded attempt.

Clean manifest status summary: five `301`, eight `200`, zero `403`, zero `429`.

## Clean URLs Probed

| Clean # | Site | Label | URL | Status | Bytes | Content-Type |
|---:|---|---|---|---:|---:|---|
| 1 | NYC | points | `https://api.weather.gov/points/40.78333,-73.96667` | 301 | 463 | `application/problem+json` |
| 2 | SFO | points | `https://api.weather.gov/points/37.61961,-122.36558` | 301 | 463 | `application/problem+json` |
| 3 | MIA | points | `https://api.weather.gov/points/25.79056,-80.31639` | 301 | 463 | `application/problem+json` |
| 4 | MDW | points | `https://api.weather.gov/points/41.78417,-87.75528` | 301 | 463 | `application/problem+json` |
| 5 | LAX | points | `https://api.weather.gov/points/33.93806,-118.38889` | 301 | 463 | `application/problem+json` |
| 6 | NYC | points_canonical | `https://api.weather.gov/points/40.7833,-73.9667` | 200 | 3,053 | `application/ld+json` |
| 7 | NYC | forecast | `https://api.weather.gov/gridpoints/OKX/34,45/forecast` | 200 | 12,422 | `application/ld+json` |
| 8 | NYC | forecast_hourly | `https://api.weather.gov/gridpoints/OKX/34,45/forecast/hourly` | 200 | 147,089 | `application/ld+json` |
| 9 | NYC | raw_gridpoint | `https://api.weather.gov/gridpoints/OKX/34,45` | 200 | 193,354 | `application/ld+json` |
| 10 | DOC | openapi | `https://api.weather.gov/openapi.json` | 200 | 121,410 | `application/vnd.oai.openapi+json;version=3.1` |
| 11 | NYC | observation_stations | `https://api.weather.gov/gridpoints/OKX/34,45/stations` | 200 | 42,523 | `application/ld+json` |
| 12 | NYC | forecast_cadence_2 | `https://api.weather.gov/gridpoints/OKX/34,45/forecast` | 200 | 12,422 | `application/ld+json` |
| 13 | NYC | forecast_cadence_3 | `https://api.weather.gov/gridpoints/OKX/34,45/forecast` | 200 | 12,422 | `application/ld+json` |

## 1. Resolution

Result: the literal registry-coordinate `/points/{lat},{lon}` URL **does not
resolve without a 3xx for any of the five sites**. All five returned 301
`Adjusting Precision Of Point Coordinate`.

| Site | Registry lat/lon | Clean status | Location |
|---|---:|---:|---|
| NYC | `40.78333,-73.96667` | 301 | `/points/40.7833,-73.9667` |
| SFO | `37.61961,-122.36558` | 301 | `/points/37.6196,-122.3656` |
| MIA | `25.79056,-80.31639` | 301 | `/points/25.7906,-80.3164` |
| MDW | `41.78417,-87.75528` | 301 | `/points/41.7842,-87.7553` |
| LAX | `33.93806,-118.38889` | 301 | `/points/33.9381,-118.3889` |

Captured excerpt from `NYC_points.json`:

```json
{
  "title": "Adjusting Precision Of Point Coordinate",
  "status": 301,
  "detail": "The precision of latitude/longitude points is limited for efficiency. The location attribute contains your request mapped to the nearest supported point. If your client supports it, you will be redirected."
}
```

Implication: the forecast URL builder cannot pass the current five-decimal
registry coordinates verbatim into the existing no-redirect transport. It must
either store/use NWS-supported rounded coordinates or canonicalize before the
GET. Following the 301 is not compatible with the current integrity posture.

For one canonical NYC follow-up, `/points/40.7833,-73.9667` resolved 200 and
returned:

```json
{
  "gridId": "OKX",
  "gridX": 34,
  "gridY": 45,
  "forecast": "https://api.weather.gov/gridpoints/OKX/34,45/forecast",
  "forecastHourly": "https://api.weather.gov/gridpoints/OKX/34,45/forecast/hourly",
  "forecastGridData": "https://api.weather.gov/gridpoints/OKX/34,45",
  "observationStations": "https://api.weather.gov/gridpoints/OKX/34,45/stations",
  "forecastOffice": "https://api.weather.gov/offices/OKX",
  "timeZone": "America/New_York",
  "radarStation": "KOKX"
}
```

The NYC canonical forecast URL resolved 200 with no 3xx. The other four
canonical point URLs and their forecast URLs were not fetched because the
request budget had already been damaged by the discarded redirect-following
attempt.

## 2. Payload Size Against 128 KiB Cap

Cap in `src/breezy/ingest/http.py`: 128 KiB = 131,072 bytes.

Measured with `Accept-Encoding: identity` for NYC canonical gridpoint `OKX/34,45`.

| Endpoint | Bytes | Difference vs 128 KiB | Result |
|---|---:|---:|---|
| `/gridpoints/OKX/34,45/forecast` | 12,422 | -118,650 | under cap |
| `/gridpoints/OKX/34,45/forecast/hourly` | 147,089 | +16,017 | **over cap** |
| `/gridpoints/OKX/34,45` | 193,354 | +62,282 | **over cap** |

Implication: D6 should not fall back to periodised `/forecast` on size alone,
but the forecast transport instance needs a cap above the measured hourly size.
The raw gridpoint endpoint is larger still and should not share the settlement
transport's default cap.

## 3. Field Names

In `NYC_forecast_hourly.json`, hourly temperature and interval fields are:

- `periods[].temperature`
- `periods[].startTime`
- `periods[].endTime`

The forecast update/issuance field is top-level:

- `updateTime`

The forecast and hourly forecast payloads also carry:

- `generatedAt`
- `validTimes`

Captured first hourly period excerpt:

```json
{
  "startTime": "2026-08-28T23:00:00-04:00",
  "endTime": "2026-08-29T00:00:00-04:00",
  "temperature": 74,
  "temperatureUnit": "F"
}
```

Raw gridpoint data uses a different shape: `temperature.values[].validTime`
and `temperature.values[].value`, with top-level `updateTime` and `validTimes`.

## 4. Temporal Semantics - Decision D6

NYC hourly `/forecast/hourly` returned 156 hourly periods.

| Field | Value |
|---|---|
| `updateTime` | `2026-08-28T18:11:31+00:00` |
| `validTimes` | `2026-08-28T12:00:00+00:00/P7DT13H` |
| First hourly `startTime` | `2026-08-28T23:00:00-04:00` |
| Last hourly `endTime` | `2026-09-04T11:00:00-04:00` |
| Observed hourly `startTime` offset set | `-0400` only |

The hourly `startTime` values are local civil time for NYC in August
(`-04:00`, EDT), not Breezy's fixed local-standard climate-day offset
(`-05:00`). This does **not** contradict D6 if the builder selects periods by
instant against the fixed-standard window.

For the NYC fixed-standard day beginning `2026-08-29T00:00:00-05:00`, the
instant window is:

- start: `2026-08-29T05:00:00Z`
- end: `2026-08-30T05:00:00Z`

Selecting hourly periods by `startTime` instant yielded 24 periods, from
`2026-08-29T01:00:00-04:00` through `2026-08-30T00:00:00-04:00`, with a max
temperature of 80 F in this captured payload.

Decision: D6 survives semantically. `/forecast/hourly` permits deriving a max
over the local-standard day, but only if the implementation converts the
fixed-standard window to instants and does not group by civil-date labels.

## 5. Update Cadence

One NYC gridpoint forecast was polled three times:

| Request | Started UTC | `generatedAt` | `updateTime` | SHA-256 |
|---:|---|---|---|---|
| 7 | `2026-08-29T03:45:17Z` | `2026-08-29T03:45:17+00:00` | `2026-08-28T18:11:31+00:00` | `ba6f523b19bf5bf5f2ce3169ff4a839ffbbf65d9300ae9614dc95f52523de6e6` |
| 12 | `2026-08-29T03:48:17Z` | `2026-08-29T03:45:17+00:00` | `2026-08-28T18:11:31+00:00` | `ba6f523b19bf5bf5f2ce3169ff4a839ffbbf65d9300ae9614dc95f52523de6e6` |
| 13 | `2026-08-29T03:51:17Z` | `2026-08-29T03:45:17+00:00` | `2026-08-28T18:11:31+00:00` | `ba6f523b19bf5bf5f2ce3169ff4a839ffbbf65d9300ae9614dc95f52523de6e6` |

Observed bound: no payload or `updateTime` change over a six-minute window.
This does not establish the true cadence. Response headers for `/forecast`
included `Cache-Control: public, max-age=3600, s-maxage=3600`, so a client
polling faster than hourly may receive cached identical bodies even if upstream
issuance behavior has its own schedule.

## 6. Archive Availability

The captured OpenAPI document exposes current gridpoint forecast endpoints:

- `/gridpoints/{wfo}/{x},{y}`
- `/gridpoints/{wfo}/{x},{y}/forecast`
- `/gridpoints/{wfo}/{x},{y}/forecast/hourly`
- `/gridpoints/{wfo}/{x},{y}/stations`

The parameter lists for the gridpoint forecast endpoints contain only:

- `GridpointWFO`
- `GridpointX`
- `GridpointY`
- `GridpointForecastFeatureFlags`
- `GridpointForecastUnits`

The raw gridpoint endpoint contains only:

- `GridpointWFO`
- `GridpointX`
- `GridpointY`

Finding: the public OpenAPI captured in this probe exposes no historical or
archived gridpoint-forecast retrieval keyed by past issuance time. This is a
narrow negative finding about gridpoint forecasts. It does not contradict the
separate fact that `/products/{productId}` serves archived text products.

Residual uncertainty: this is based on the public OpenAPI document, not an
exhaustive brute-force search for undocumented endpoints.

## 7. `/points` Stability And Cache Signal

The exact five-decimal `/points` responses returned 301 with:

- `Cache-Control: private, max-age=86296` on the NYC sample
- `Expires: Sun, 30 Aug 2026 03:42:09 GMT`

The canonical NYC `/points/40.7833,-73.9667` response returned 200 with:

- `Cache-Control: public, max-age=86217, s-maxage=120`
- `Expires: Sun, 30 Aug 2026 03:42:09 GMT`

Interpretation: `/points` is explicitly cacheable on the order of one day for
the client, while shared-cache freshness was 120 seconds. This supports caching
the point-to-grid mapping within a poll cycle and likely within a day, but it
does not prove week-level grid assignment stability. A weekly re-resolution
control remains a reasonable integrity check; the implementation should also
record `gridId`, `gridX`, and `gridY` on every forecast record as planned.

The more immediate finding is that the registry coordinate precision must be
canonicalized before a no-redirect `/points` GET.

## 8. Station/Grid Binding

NYC was checked. The canonical NYC `/points` response resolved to
`OKX/34,45`, whose `observationStations` list contained 40 stations and included
`https://api.weather.gov/stations/KNYC` as the first entry.

Result for NYC: pass for the station-list binding spot check.

SFO, MIA, MDW, and LAX were not checked because the 301 behavior and the
discarded redirect-following attempt consumed the request budget. They remain a
required follow-up before I-1 freezes the field set.

## Could Not Determine

- All-five canonical forecast resolution: the literal registry-coordinate
  `/points` URLs returned 301 for all five sites. Fetching all five canonical
  points and all five returned forecast URLs would have exceeded the already
  damaged request budget.
- All-five station/grid binding: only NYC was checked. Four station-list
  requests remain for SFO, MIA, MDW, and LAX.
- True forecast update cadence: three NYC forecast samples over six minutes did
  not change, and the response cache allows one-hour freshness. This bounds only
  this short observation window.
- Hidden/undocumented historical gridpoint forecast archive endpoints: OpenAPI
  exposed none, but no brute-force endpoint search was attempted because of the
  request budget and UA-trap risk.

## Plan Changes Recommended

1. I-1 must canonicalize or pre-store NWS-supported rounded point coordinates
   before calling `/points`; current five-decimal registry coordinates return
   301 and are incompatible with no-redirect transport.
2. Forecast transport needs its own `max_body_bytes` above the measured
   `/forecast/hourly` payload size. A cap near the raw gridpoint size is not
   justified unless raw gridpoint retrieval becomes part of the design.
3. D6 should stay: derive from `/forecast/hourly`, but select hourly periods by
   instant against the fixed local-standard window.
4. Leave periodised `/forecast` as degraded fallback only. It fits under 128 KiB
   but cannot solve the local-standard temporal window correctly.
5. Complete station/grid binding for SFO, MIA, MDW, and LAX in a separate,
   tightly budgeted follow-up.
