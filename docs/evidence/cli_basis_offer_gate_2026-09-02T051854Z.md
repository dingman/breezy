# CLI-basis candidate #2 -- offer-gate scan (daily)

Generated 2026-09-02T05:20:23Z
- Quote tape: `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`
- ASOS cache (cache-only, zero network): `/home/jon/.local/share/breezy/archive/settlement-alignment-cache`
- Regenerate: `.venv/bin/python scripts/analysis/cli_basis_offer_gate_scan.py`

## 1. Tape-instance preflight

| Instance | Verdict | Rows |
|---|---|---:|
| `1744b9cf-527c-4b59-9250-ad8e480c17ea` | EMPTY | 0 |
| `3dd59abf-7656-4831-a5ab-3dee4e7928ab` | CLEAN | 52097 |
| `43749af1-0f3e-4de1-8d5e-746c7db072f5` | CLEAN | 4319 |
| `50ed2c68-95c5-440f-8edc-883b352042b7` | LIVE | 18611 |
| `5a111bca-c349-49d7-94bc-948649485ac8` | CLEAN | 952453 |
| `711ac111-c51a-4233-9af9-a518e101b466` | CLEAN | 38341 |
| `7dc3d1c0-cf8d-4acf-bfa0-8c1f3572e538` | CLEAN | 671552 |

Excluded (not an open upper-tail rung, or facts/slug disagreed): 368
Ask-side depth-truncated snapshots observed: 100208 (truncation drops only DEEPER, more expensive levels -- see module docstring; a cheap qualifying ask is never hidden by it, but total notional under truncation is a lower bound).

## 2. ASOS cache coverage found (BL-24: no live intraday ingest)

| Station | Cached rows found |
|---|---:|
| LAX | 569459 |
| MDW | 571401 |
| MIA | 568719 |
| NYC | 56004 |
| SFO | 568465 |

## 3. Per station-day results

| Station | Climate day | Dense? | Admissible | Event | Qualifying instants | Best ask | Size | Max notional | Blocked reason |
|---|---|:--:|:--:|:--:|---:|---:|---:|---:|---|
| LAX | 2026-08-30 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| LAX | 2026-08-31 | dense | yes | YES | 1630 | 0.01 | 160.00 | 185.5700 | - |
| LAX | 2026-09-01 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MDW | 2026-08-30 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MDW | 2026-08-31 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MDW | 2026-09-01 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MIA | 2026-08-30 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MIA | 2026-08-31 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| MIA | 2026-09-01 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| NYC | 2026-08-30 | CONTAMINATED | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| NYC | 2026-08-31 | CONTAMINATED | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| NYC | 2026-09-01 | CONTAMINATED | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| SFO | 2026-08-30 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| SFO | 2026-08-31 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |
| SFO | 2026-09-01 | dense | no | no | 0 | - | - | 0 | ASOS coverage never reached a headroom-1-or-2 instant this station-day |

### Hour-of-day breakdown (diagnostic only -- NOT a gate; see docstring)

- LAX 2026-08-31: 16:00=233, 19:00=192, 20:00=191, 21:00=475, 22:00=539

## 4. Pre-registered kill / GO rule

`n` counts admissible DENSE (non-NYC) station-days only; `k` counts those with >= 1 qualifying event.
n = 1, k = 1, Wilson 95% lower = 0.2065, upper = 1.0000

**UNDERPOWERED**

Needs n >= 50 admissible dense station-days to reach a decisive verdict either way. Re-run as capture and the ASOS cache accumulate.

