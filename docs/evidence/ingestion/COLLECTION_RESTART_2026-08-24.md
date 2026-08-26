# Collection restart after total catalog loss — 2026-08-24

**Captured:** 2026-08-24T20:04:40Z
**Process:** systemd user unit `breezy-nws-ingest.service`, PID 371915,
started 2026-08-24T19:45:54Z, `NRestarts=0`.

This document records a cold start of NWS collection on new durable storage
after the catalog described in `LIVE_RUN_2026-08-24.md` was found to be gone.
Every figure below is copied from the service journal or from the filesystem,
not reconstructed.

---

## 1. Precondition: the prior catalog did not exist

Verified before starting: no parquet, no `breezy-state*`, and no bootstrap
witness existed anywhere under `/home/jon`, and `BREEZY_CATALOG_BASE` was
unset in the environment. Nothing was collecting.

## 2. Storage

```
BREEZY_CATALOG_BASE=/home/jon/.local/share/breezy/catalog   (0700)
filesystem: ext4, 543G available   <- verified NOT tmpfs
state DB:   <base>/state/breezy-state.sqlite3  (derived, not configured)
```

Durability guard armed on first boot:

```
runtime:bootstrap_witness   b'1'
durability:probe            b'3d1b6d13ed49469e9f1ba6ada3a18e27'
```

## 3. Cold-start gate behaviour (fail-closed, as designed)

At 19:50:55Z, with no history, every site was BLOCKED:

```
gate transition venue=polymarket_us city=SFO state=BLOCKED reason=final_cli_overdue detail=no final CLI for SFO 2026-08-23 by the venue deadline
gate transition venue=polymarket_us city=LAX state=BLOCKED reason=final_cli_overdue detail=no final CLI for LAX 2026-08-23 by the venue deadline
gate transition venue=polymarket_us city=NYC state=BLOCKED reason=final_cli_overdue detail=no final CLI for NYC 2026-08-23 by the venue deadline
gate transition venue=polymarket_us city=MDW state=BLOCKED reason=final_cli_overdue detail=no final CLI for MDW 2026-08-23 by the venue deadline
gate transition venue=polymarket_us city=MIA state=BLOCKED reason=final_cli_overdue detail=no final CLI for MIA 2026-08-23 by the venue deadline
```

Retention pressure at the same instant (NYC shown; the CRITICAL on 2026-08-17
is a zero-margin warning):

```
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=CRITICAL detail=climate day 2026-08-17 is open with 0 day(s) until assumed retention loss
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=CRITICAL detail=climate day 2026-08-18 is open with 1 day(s) until assumed retention loss
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=CRITICAL detail=climate day 2026-08-19 is open with 2 day(s) until assumed retention loss
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=WARN     detail=climate day 2026-08-20 is open with 3 day(s) until assumed retention loss
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=WARN     detail=climate day 2026-08-21 is open with 4 day(s) until assumed retention loss
breezy alert event=gap_retention_warning site=polymarket_us/NYC severity=WARN     detail=climate day 2026-08-22 is open with 5 day(s) until assumed retention loss
```

## 4. Backfill: seven climate days per site

NYC, verbatim, 19:50:55Z -> 19:51:04Z — both product tiers for each of
2026-08-17 .. 2026-08-23:

```
polymarket_us/NYC prepared PRELIMINARY product af3c462d-eef6-4f40-8805-c1dd03cf53a6 for climate day 2026-08-17 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product cc0c347d-0304-4dba-93f7-5931f5ebb078 for climate day 2026-08-17 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product bc5858c8-4560-4d32-b1ba-c7fad5746c2d for climate day 2026-08-18 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product 27d7f04f-2b4d-42dd-ba6a-1f3c1d1c665b for climate day 2026-08-18 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product ccca313f-5bd2-4dfc-bc58-11bb0f75c578 for climate day 2026-08-19 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product a4369b2b-2362-4ec7-a51a-fda051f782c3 for climate day 2026-08-19 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product 0dda45a4-a9a7-4313-b8ba-967f41d05ebd for climate day 2026-08-20 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product a85eb8d8-d48e-4584-8d4d-ef230c5810c1 for climate day 2026-08-20 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product c52effd7-d893-47ba-85ff-037f7ceee51f for climate day 2026-08-21 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product 40bb657c-e166-44d4-a038-dd18701cf2c8 for climate day 2026-08-21 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product 19841454-e261-4107-b6ac-a1bd0d7bf46f for climate day 2026-08-22 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product 920ae9d2-6c4d-48a9-aa7a-c3dec3256941 for climate day 2026-08-22 (correction_evidence=False)
polymarket_us/NYC prepared PRELIMINARY product 2ba97e44-fb08-468a-8477-bdf11c8a6b8b for climate day 2026-08-23 (correction_evidence=False)
polymarket_us/NYC prepared FINAL       product 3eb9851b-add5-4e86-a9ca-d1070adeb852 for climate day 2026-08-23 (correction_evidence=False)
```

## 5. Persistence and gate open, all five sites

```
19:51:04Z polymarket_us/NYC poll outcome=persisted action=record_successful_poll: wrote 28 record(s)
19:52:03Z polymarket_us/SFO poll outcome=persisted action=record_successful_poll: wrote 28 record(s)
19:53:04Z polymarket_us/MIA poll outcome=persisted action=record_successful_poll: wrote 28 record(s)
19:54:04Z polymarket_us/MDW poll outcome=persisted action=record_successful_poll: wrote 30 record(s)
19:55:08Z polymarket_us/LAX poll outcome=persisted action=record_successful_poll: wrote 38 record(s)
```

All five then transitioned:

```
state=OPEN reason=final_received detail=final received for climate_day=2026-08-23
```

On disk — 2 parquet datasets per site (`custom_nws_climate_day`,
`custom_nws_raw_product`):

```
NYC   2 parquet  48K
SFO   2 parquet  48K
MIA   2 parquet  48K
MDW   2 parquet  64K
LAX   2 parquet  52K
```

## 6. Stagger verified against prediction

`site_stagger_offset_seconds(index, 5, 300)` yields 0/60/120/180/240s.

| Site | Predicted | Actual | Delta |
|---|---|---|---|
| NYC | 19:50:55 | 19:51:04 | +9s |
| SFO | 19:51:55 | 19:52:03 | +8s |
| MIA | 19:52:55 | 19:53:04 | +9s |
| MDW | 19:53:55 | 19:54:04 | +9s |
| LAX | 19:54:55 | 19:55:08 | +13s |

The delta is backfill work per cycle, not scheduling drift.

---

## Claims this run supports

1. **The fail-closed SettlementGate behaves as specified on live data** —
   BLOCKED with no history, OPEN only on a real FINAL product. Not a test.
2. **The anti-UA-trap stagger behaves as specified** — one request per 60s to
   `api.weather.gov`, never a five-way burst.
3. **MDW has a live proof**, closing the last unproven venue site.
4. **Seven climate days x five sites were recovered from NWS retention**, the
   oldest with zero days of margin.

## Claims this run does NOT support

- **Nothing here is a tradeable signal.** These are settlement truth and
  training labels only.
- **The non-uniform record counts (28/28/28/30/38) are NOT explained.** The
  correction/revision hypothesis for MDW (+2) and LAX (+10) is an inference
  from counts alone; extra METAR observations fit equally well. Unverified.
- **No digest re-verification by a separate process was performed** for this
  run, unlike the (now-lost) 2026-08-23 run. Records are persisted; they have
  not been independently read back.
