# IEM ASOS same-day availability latency — 2026-09-04 (BL-24 least-confident decision 2)

Read-only probe, 4 requests to `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`
(`data=metar`, `tz=Etc/UTC`, `format=onlycomma`, `report_type=1&report_type=2`, window
[now−3h, now+1h]), UA from `BREEZY_USER_AGENT`. Times UTC.

| poll | station | rows | newest `valid` | wall clock | lag |
|---|---|---|---|---|---|
| 01:27 | KNYC | 3 | 00:51 | 01:27:19 | 36.5 min |
| 01:27 | KMDW | 37 | 00:53 | 01:27:31 | 34.5 min |
| 01:34 | KNYC | 3 | 00:51 (no new rows) | 01:34:15 | 43.3 min |
| 01:34 | KMDW | 41 | 01:15 (+4 rows: 01:00–01:15) | 01:34:20 | 19.3 min |

**Cadence.** KNYC (Central Park) is HOURLY only (obs at :51; no 5-minute rows at all).
KMDW carries 5-minute rows plus the :53 routine METAR; a 00:55 row was absent in both polls.
The 5-minute stream arrives in batches; availability lag oscillated 19–35 min, never under
15 min. No rate-limit or `Retry-After` headers in-band.

**On disk.** Nightly refresh cache newest mtime epoch 1788475547 (22:45:47Z), newest
`valid` 22:30 — ~15 min in-file lag at fetch, ~3 h stale by 01:27 (refresh is nightly).
`fetch_text_cached` is URL-keyed and would serve a same-day re-fetch from cache.

**Verdict: 15–60 min.** Not timely enough for a lag-10/15 live rule on this endpoint.
Consequences: (1) BL-24 Seam B's staleness bound must be per station and ≥ ~45 min for NYC;
(2) the live rule's effective lag on IEM is ~20–45 min, which is NOT the lag M_B measured
(5/10/15) — a live measurement at that lag is a different pre-registered rule and must be
designed as such (Grok); (3) alternative sources (NWS `observations/latest`, IEM
`api/1/currents`, FAA AWC METAR) need their own latency probe before Seam B is briefed.
