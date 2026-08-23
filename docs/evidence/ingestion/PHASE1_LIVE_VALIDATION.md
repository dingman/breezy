# Phase 1 NWS Ingestion — Live Validation Evidence

Captured 2026-08-23 at commit `4f177da`, against live `api.weather.gov`.
No mocks, no fixtures, no recorded responses. Site: `polymarket_us:NYC` (Central Park).

Reproduce with `BREEZY_SITES`, `BREEZY_CATALOG_BASE`, `BREEZY_STATE_DB`,
`BREEZY_POLL_INTERVAL_SECONDS` and `BREEZY_USER_AGENT` set, then `uv run breezy`.

## 1. Steady-state polling actually re-contacts NWS

Earlier runs proved only warm-start backfill: every product arrived in a ~1.6s
burst at startup, and later cycles added nothing because NWS publishes CLI once
daily. Repeated polling was therefore ASSUMED, not proven. This test proves it by
sampling the gate's durable `last_successful_poll_ns` from a separate reader
process while the node ran, with `BREEZY_POLL_INTERVAL_SECONDS=20`:

```
t+ 20s  poll #1  last_successful_poll_ns=1787514993046827694
t+ 40s  poll #2  last_successful_poll_ns=1787515011038598991   gap 18.0s
t+ 60s  poll #3  last_successful_poll_ns=1787515031136436069   gap 20.1s
t+ 80s  poll #4  last_successful_poll_ns=1787515051007743540   gap 19.9s
t+100s  poll #5  last_successful_poll_ns=1787515071089353364   gap 20.1s
```

Final gate state: `last_reason=successful_poll`,
detail `discovery list carried 14 product(s), none new`, `ua_trap_blocked=False`.

## 2. Retrieved, stored, ingested, readable by a separate process

```
CATALOG
======================================================================

  [polymarket_us/NYC]  exists=True
    climate_days=14  raw_products=14
    ts_init non-decreasing: True
    settlement digests verified: 14/14 all_ok=True
      2026-08-16  tmax=80 tmin=71 final=False  ts_event=2026-08-16T20:33:00+00:00
      2026-08-16  tmax=80 tmin=67 final=True  ts_event=2026-08-17T05:00:00+00:00
      2026-08-17  tmax=80 tmin=68 final=False  ts_event=2026-08-17T20:44:00+00:00
      2026-08-17  tmax=81 tmin=68 final=True  ts_event=2026-08-18T05:00:00+00:00
      2026-08-18  tmax=86 tmin=72 final=False  ts_event=2026-08-18T20:33:00+00:00
      2026-08-18  tmax=86 tmin=72 final=True  ts_event=2026-08-19T05:00:00+00:00
      2026-08-19  tmax=85 tmin=69 final=False  ts_event=2026-08-19T20:32:00+00:00
      2026-08-19  tmax=85 tmin=69 final=True  ts_event=2026-08-20T05:00:00+00:00
      2026-08-20  tmax=84 tmin=71 final=False  ts_event=2026-08-20T20:45:00+00:00
      2026-08-20  tmax=84 tmin=63 final=True  ts_event=2026-08-21T05:00:00+00:00
      2026-08-21  tmax=79 tmin=63 final=False  ts_event=2026-08-21T20:44:00+00:00
      2026-08-21  tmax=79 tmin=63 final=True  ts_event=2026-08-22T05:00:00+00:00
      2026-08-22  tmax=77 tmin=67 final=False  ts_event=2026-08-22T20:39:00+00:00
      2026-08-22  tmax=77 tmin=67 final=True  ts_event=2026-08-23T05:00:00+00:00
      raw uuid: 0dda45a4-a9a7-4313-b8ba-967f41d05ebd
      raw uuid: 19841454-e261-4107-b6ac-a1bd0d7bf46f
      raw uuid: 27d7f04f-2b4d-42dd-ba6a-1f3c1d1c665b
      raw uuid: 40bb657c-e166-44d4-a038-dd18701cf2c8
      raw uuid: 920ae9d2-6c4d-48a9-aa7a-c3dec3256941
      raw uuid: a4369b2b-2362-4ec7-a51a-fda051f782c3
      raw uuid: a85eb8d8-d48e-4584-8d4d-ef230c5810c1
      raw uuid: af3c462d-eef6-4f40-8805-c1dd03cf53a6
      raw uuid: bc5858c8-4560-4d32-b1ba-c7fad5746c2d
```

## 3. Node and actor lifecycle

```
2026-08-23T15:55:00.289812588Z [INFO] BREEZY-001.TradingNode: has_cache_backing=False
2026-08-23T15:55:00.289813927Z [INFO] BREEZY-001.TradingNode: has_msgbus_backing=False
2026-08-23T15:55:00.289891487Z [INFO] BREEZY-001.BREEZY-001: Registered Component NWS-INGEST-polymarket_us-NYC
2026-08-23T15:55:00.290838404Z [INFO] BREEZY-001.NWS-INGEST-polymarket_us-NYC: RUNNING
```

No Redis, no message-bus backing, and ZERO catalogs registered with the DataEngine
(`DataEngine._query_catalog` breaks on the first registered catalog returning rows).

## 4. Restart dedupe

A second full process over the SAME catalog and state (95s, 30s polls) held at
`raw_products=14`, `climate_days=14`, 14 unique UUIDs, all digests valid.

## What this evidence does NOT cover

- Ingestion of a **newly published** product mid-run was never observed: none was
  published during any test window. Cycles 2+ exercised the dedupe path
  (`none new`), which is correct behaviour but is not the same proof.
- Only `polymarket_us:NYC` was live-exercised. SFO, MIA, MDW and LAX are
  configured in `sites.toml` but untested against the live API.
- The design's pre-production gate (`sites.toml:94-104`) — independent live
  re-verification of each site's `issuing_office` and `body_header_regex` — has
  NOT been run. That, not this document, is the settlement-truth check.
