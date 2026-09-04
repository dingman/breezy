# Live observation sources — latency and cadence census (2026-09-04, ~01:36Z)

Follow-up to `iem_asos_live_latency_2026-09-04.md`. Single polls (one draw each from a
batchy arrival process); UA from `BREEZY_USER_AGENT`; 11 requests.

| source | station | cadence | newest obs | lag |
|---|---|---|---|---|
| NWS `api.weather.gov/stations/{icao}/observations` | KMDW | **5-min** rows + :53 METAR | 01:15 | 21 min |
| NWS same | KNYC | hourly :51 only | 00:51 | 45 min |
| IEM `api/1/currents.json` | MDW / NYC | METAR only | 00:53 / 00:51 | 43 / 45 min |
| IEM `asos1min.py` | MDW / NYC | **0 rows** (both 09-03 and 09-04) | — | unproven |
| FAA AWC `api/data/metar` | KMDW / KNYC | METAR hourly; receipt ~3.5 min after obs | 00:53 / 00:51 | 44 / 46 min |

Findings:
- **KNYC (Central Park) has no sub-hourly observations in any public source.** A ≤15-min
  running-max rule is not satisfiable for NYC.
- **NWS API is the only sub-hourly source** for the ASOS 5-minute stations, ~20–35 min behind
  (prior IEM CSV: 19–43 min). Its 5-minute rows carry **integer °C** (e.g. 29) with an empty
  `rawMessage`; only the hourly METAR carries tenths (29.4). Integer °C spans ~1.8 °F, i.e.
  up to two 1 °F rungs — a 5-minute row bounds R(t) but does not place the rung exactly.
- The host `api.weather.gov` is already in `DEFAULT_ALLOWED_HOSTS`; the settlement
  transport's hardening applies unchanged. NWS `cache-control: max-age=92`.
- AWC returned a 504 once and succeeded on retry; IEM/NWS/AWC publish no rate-limit headers.

Consequences for BL-24 Seam B and the live-small rule:
1. Source: NWS API observations JSON (not IEM CSV) for the 5-minute stations; KNYC is
   hourly-only and its staleness bound must admit ≥60 min or NYC is excluded from the rule.
2. `R(t)` from 5-minute rows is a **bounded interval** (integer °C → [x−0.5, x+0.5) °C),
   exact only at the hourly METAR. The accumulator must carry the precision of each row.
3. The achievable live lag (~20–45 min) is not the lag M_B measures (5/10/15). The
   live-small rule must be designed and pre-registered at the achievable lag (Grok), and the
   M_B daily study should add matching lag arms so the live and archive measurements agree.
