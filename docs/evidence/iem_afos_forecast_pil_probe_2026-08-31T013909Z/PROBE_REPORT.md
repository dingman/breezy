# IEM AFOS forecast-PIL probe (P2 Probe B)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into any production catalog.

**A forecast archive cannot produce a backtest, because a backtest also
needs prices, and prices are forward-only and permanently
unrecoverable.** What a forecast archive produces is a forecast-error /
calibration dataset.

Host: `mesonet.agron.iastate.edu` (settlement host NOT touched)
Transport: `breezy.ingest.probe_transport.ProbeTransport`, max_body_bytes=4194304
Request budget: 12 hard; spent 4.
Planned steps: 4; dispatched: 4.

## Outcomes

| # | label | status | bytes | outcome |
|--:|---|--:|--:|---|
| 1 | `afd_nyc` | 200 | 364281 | ok |
| 2 | `zfp_nyc` | 200 | 3341327 | ok |
| 3 | `afd_mdw` | 200 | 385891 | ok |
| 4 | `zfp_mdw` | 200 | 4102198 | ok |

## Step coverage

- `afd_nyc`: YIELDED 60 product(s) for NYC (WMO-headed: 59)
- `zfp_nyc`: YIELDED 60 product(s) for NYC (WMO-headed: 60)
- `afd_mdw`: YIELDED 60 product(s) for MDW (WMO-headed: 59)
- `zfp_mdw`: YIELDED 60 product(s) for MDW (WMO-headed: 60)

## Findings

- No non-2xx response and no transport alarm was recorded.

## Pre-registered bar

| clause | measured | bar | state |
|---|---|---|---|
| products | 240 | >= 50 | PASS |
| sites (distinct cities) | 2 | >= 2 | PASS |
| parse rate | 0.5125 (123/240) | >= 0.9 | FAIL |
| issuance from WMO header | 238/240 | all | FAIL |
| office attribution | 238/240 | all | FAIL |

Parse rate, as a number: **0.5125** (123 numeric daily highs from 240 products).

### What the attribution clause actually checked

The plan phrases this clause as containment in a UGC zone. True UGC-zone
geometry is NOT in the site registry, and `sites.toml` forbids deriving an
identifier, so no zone -> station mapping was invented. What was checked is
an OFFICE match: the WMO header's `KXXX` against the registry's
`issuing_office` for the settlement station. That is weaker than zone
containment and is reported under its own name rather than the stronger one.

### Failing clauses

- parse_rate: 0.5125 < 0.9 required (123/240 numeric daily highs)
- issuance_time: recoverable from the WMO header on 238/240 products; all are required
- office_attribution: 238/240 products whose WMO-header office matches the registry `issuing_office` for the settlement station; all are required

**The correct response to this FAIL is to STOP.** Writing a
forecast-text parser to lift the rate is a research project
masquerading as an ingestion increment (plan section 4.P2).


VERDICT: FAIL
