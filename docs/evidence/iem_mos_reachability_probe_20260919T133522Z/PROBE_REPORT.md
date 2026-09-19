# IEM MOS (NBS/GFS) reachability probe (FC-0a-1)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into any production catalog.

Host: `mesonet.agron.iastate.edu` (settlement host NOT touched)
Transport: `iem_mos_probe_transport.IemMosProbeTransport`, max_body_bytes=33554432
Request budget: 56 hard; spent 48.
Planned steps: 48; year-cells: 48.
max_body_bytes_measured: 5067326

## Per-station NBS spans

- `KLAX` first=2021-01-01T01:00:00+00:00 last=2026-09-19T12:00:00+00:00 total_rows=194258
  - 2021: rows=33488 distinct_runtime_days=365 first=2021-01-01 01:00:00 last=2021-12-31 19:00:00
  - 2022: rows=33534 distinct_runtime_days=365 first=2022-01-01 01:00:00 last=2022-12-31 19:00:00
  - 2023: rows=33580 distinct_runtime_days=365 first=2023-01-01 01:00:00 last=2023-12-31 19:00:00
  - 2024: rows=33626 distinct_runtime_days=366 first=2024-01-01 01:00:00 last=2024-12-31 19:00:00
  - 2025: rows=33580 distinct_runtime_days=365 first=2025-01-01 01:00:00 last=2025-12-31 19:00:00
  - 2026: rows=26450 distinct_runtime_days=262 first=2026-01-01 01:00:00 last=2026-09-19 12:00:00
- `KMDW` first=2021-01-01T01:00:00+00:00 last=2026-09-19T12:00:00+00:00 total_rows=194189
  - 2021: rows=33419 distinct_runtime_days=365 first=2021-01-01 01:00:00 last=2021-12-31 19:00:00
  - 2022: rows=33534 distinct_runtime_days=365 first=2022-01-01 01:00:00 last=2022-12-31 19:00:00
  - 2023: rows=33580 distinct_runtime_days=365 first=2023-01-01 01:00:00 last=2023-12-31 19:00:00
  - 2024: rows=33626 distinct_runtime_days=366 first=2024-01-01 01:00:00 last=2024-12-31 19:00:00
  - 2025: rows=33580 distinct_runtime_days=365 first=2025-01-01 01:00:00 last=2025-12-31 19:00:00
  - 2026: rows=26450 distinct_runtime_days=262 first=2026-01-01 01:00:00 last=2026-09-19 12:00:00
- `KMIA` first=2021-01-01T01:00:00+00:00 last=2026-09-19T12:00:00+00:00 total_rows=194281
  - 2021: rows=33511 distinct_runtime_days=365 first=2021-01-01 01:00:00 last=2021-12-31 19:00:00
  - 2022: rows=33534 distinct_runtime_days=365 first=2022-01-01 01:00:00 last=2022-12-31 19:00:00
  - 2023: rows=33580 distinct_runtime_days=365 first=2023-01-01 01:00:00 last=2023-12-31 19:00:00
  - 2024: rows=33626 distinct_runtime_days=366 first=2024-01-01 01:00:00 last=2024-12-31 19:00:00
  - 2025: rows=33580 distinct_runtime_days=365 first=2025-01-01 01:00:00 last=2025-12-31 19:00:00
  - 2026: rows=26450 distinct_runtime_days=262 first=2026-01-01 01:00:00 last=2026-09-19 12:00:00
- `KSFO` first=2021-01-01T01:00:00+00:00 last=2026-09-19T12:00:00+00:00 total_rows=194235
  - 2021: rows=33511 distinct_runtime_days=365 first=2021-01-01 01:00:00 last=2021-12-31 19:00:00
  - 2022: rows=33511 distinct_runtime_days=365 first=2022-01-01 01:00:00 last=2022-12-31 19:00:00
  - 2023: rows=33580 distinct_runtime_days=365 first=2023-01-01 01:00:00 last=2023-12-31 19:00:00
  - 2024: rows=33603 distinct_runtime_days=366 first=2024-01-01 01:00:00 last=2024-12-31 19:00:00
  - 2025: rows=33580 distinct_runtime_days=365 first=2025-01-01 01:00:00 last=2025-12-31 19:00:00
  - 2026: rows=26450 distinct_runtime_days=262 first=2026-01-01 01:00:00 last=2026-09-19 12:00:00

## Four-station INTERSECTION span

INTERSECTION: 2021-01-01T01:00:00+00:00 .. 2026-09-19T12:00:00+00:00

VERDICT: PASS
