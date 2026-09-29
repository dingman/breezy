# NBP publication-lag census (S1 SL-3)

**Date:** 2026-09-29 · **Author:** tdd-guide (build agent, blind) · **Slug:** `nbp_lag_census`

**Source plan:** `docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §3.2
item 2 ("Publication-lag floor") and §7 SL-1b/SL-3. Feeds SL-1b, which pins
`MINIMUM_PUBLICATION_LAG_NS` for `"NBM_NBP"` in `forecast_point.py`.

**Method.** Unauthenticated `GET https://noaa-nbm-grib2-pds.s3.amazonaws.com/
?list-type=2&prefix=blend.{YYYYMMDD}/{HH}/text/blend_nbptx&max-keys=5` for
each (date, cycle) pair — listing only, no object bodies fetched. Lag is
defined as `S3 LastModified − nominal cycle instant` (`{date} {HH}:00 UTC`).

**Reproducibility (committed, not scratchpad).** The collection script is
`scripts/analysis/nbp_lag_census.py` — read-only, listing-only, stdlib-only
(imports neither `breezy` nor `nautilus_trader`); it does NO network I/O by
default (`--live` plus `BREEZY_LIVE=1` are both required to actually run
it), and re-running it with `--today 2026-09-29` reproduces this exact
60-date sample. Its pure core (version-era classification, the fixed
sample-date set, and parsing a `LastModified` out of a raw listing) is unit
tested in `tests/unit/test_nbp_lag_census.py`.

The derived records this note's tables are computed from are committed at
`docs/evidence/data/NBP_LAG_CENSUS_2026-09-29_records.json`
(`listing_<date>_<hh>z_<index>.xml` naming was used for the raw per-request
files during collection; sha256 of the committed records file:
`d31d6436ffda7e24f40c0e2f264caf205c8ff448ef2e9df2722c67bf933ac731`). A
representative raw `ListObjectsV2` XML listing — one per NBM version era, all
for the live-relevant 13Z cycle — is committed at
`docs/evidence/data/nbp_lag_census_raw/{v4.0_2021-09-29,v4.1_2023-01-20,
v4.2_2024-05-20,v4.3_2025-06-01,v5.0_2026-09-28}_13z.xml`; the full 360-file
raw set from the original collection run remains in the session scratchpad
only (not committed — the 5 committed samples are sufficient to show the
listing shape and to spot-check the derived records against the source XML).

## Sample

- **Cycles:** 00Z, 01Z, 07Z, 12Z, 13Z, 19Z.
- **Dates:** 60 distinct dates — the 30 calendar days ending 2026-09-29
  (2026-08-31..2026-09-29), plus 30 dates spread across 2021-2026, chosen to
  bracket every NBM version era boundary named in the plan/ruling:
  - v4.0 from 2020-09-29 (sampled: 2021-01-15, 2021-06-15, 2021-09-29,
    2021-11-15, 2022-02-15, 2022-06-15, 2022-10-15, 2023-01-10)
  - v4.1 from 2023-01-17 (sampled: 2023-01-20, 2023-06-15, 2023-11-15,
    2024-02-15, 2024-05-10)
  - v4.2 from 2024-05-15 (sampled: 2024-05-20, 2024-08-15, 2024-11-15,
    2025-02-15, 2025-05-20)
  - v4.3 from 2025-05-27 (sampled: 2025-06-01, 2025-08-15, 2025-11-15,
    2026-01-15, 2026-03-15, 2026-04-28)
  - v5.0 from 2026-05-04 (sampled: 2026-05-10, 2026-05-20, 2026-06-15,
    2026-07-15, 2026-08-01, 2026-08-15, plus every day 2026-08-31..2026-09-29
    from the last-30-days window)
- **Total requests:** 360 (60 dates x 6 cycles). **Coverage:** 359/360 OK.
  The one miss is `2026-09-29 19Z`, which had not yet been published at
  collection time (18:42Z, before its own 19:00Z nominal cycle instant) — not
  a data-quality issue, excluded from the census as not-yet-existing rather
  than as a gap.

## Archive re-upload artefacts: none found

For every version era, every sampled date's object `LastModified` falls on
the **same calendar day** as that object's own nominal cycle date (verified
across all 359 OK records, 2021 through 2026 — see the per-version
`LastModified`-date breakdown derivable from
`docs/evidence/data/NBP_LAG_CENSUS_2026-09-29_records.json`). A bulk archive
backfill would show many different, widely separated cycle dates sharing one
common `LastModified` day (the day the backfill job ran); no such clustering
appears anywhere in the sample, including the oldest v4.0 dates from 2021.
**Conclusion: this bucket's `LastModified` values are original per-cycle
publication timestamps, not backfill artefacts, at every sampled point.**

Two genuine same-day **late-publication** events were found (not excluded —
same-day, not a re-upload signature, just an operationally slow cycle):

| Date | Cycle | Version | Lag | LastModified |
|---|---|---|---|---|
| 2026-09-24 | 00Z | v5.0 | 857.2 min (14.3 h) | 2026-09-24T14:17:12Z |
| 2026-09-24 | 01Z | v5.0 | 804.2 min (13.4 h) | 2026-09-24T14:24:12Z |
| 2026-09-24 | 07Z | v5.0 | 520.1 min (8.7 h) | 2026-09-24T15:40:09Z |
| 2023-01-20 | 07Z | v4.1 | 488.3 min (8.1 h) | 2023-01-20T15:08:18Z |

2026-09-24 looks like a real production slowdown affecting three consecutive
early-morning cycles that day (00/01/07Z all delayed by hours, but the
afternoon/evening cycles that day were not — see the full per-cycle table
below, which is unaffected because the floor and per-cycle summaries below
use MIN/median/p95, not a mean, so a handful of slow days do not distort
them). These are included in `max` columns below (which is why `max` is much
larger than `p95` for 00Z/01Z/07Z and for v4.1/v5.0) but do not affect the
floor, which is a **minimum**.

## Per-cycle lag (minutes), all versions pooled, n=60 per cycle (59 for 19Z)

| Cycle | n | min | p5 | median | p95 | max |
|---|---|---|---|---|---|---|
| 00Z | 60 | 50.8 | 57.0 | 77.0 | 84.0 | 857.2 |
| 01Z | 60 | 58.0 | 61.7 | 66.9 | 98.4 | 804.2 |
| 07Z | 60 | 61.5 | 62.3 | 77.0 | 101.7 | 520.1 |
| 12Z | 60 | 52.1 | 53.6 | 86.7 | 107.6 | 250.2 |
| 13Z | 60 | 61.3 | 62.5 | 65.5 | 104.0 | 136.5 |
| 19Z | 59 | 56.6 | 62.5 | 77.0 | 97.0 | 193.1 |

## Per-version-era lag (minutes), all cycles pooled

| Version | n | min | p5 | median | p95 | max |
|---|---|---|---|---|---|---|
| v4.0 | 48 | 58.0 | 61.7 | 80.2 | 100.4 | 143.1 |
| v4.1 | 30 | 50.8 | 56.7 | 91.8 | 191.7 | 488.3 |
| v4.2 | 30 | 51.9 | 52.1 | 62.8 | 69.8 | 70.6 |
| v4.3 | 36 | 53.5 | 53.6 | 64.2 | 73.2 | 81.5 |
| v5.0 | 215 | 61.0 | 62.8 | 76.7 | 100.5 | 857.2 |

## Proposed floor

The plan (§3.2 item 2) defines the floor as: *"the minimum observed lag
across the live-relevant cycles 13Z/19Z/01Z for v5.0, rounded down to 5
min."*

- Live-relevant v5.0 records (13Z, 19Z, 01Z): n = 107.
- Minimum observed lag: **61.05 minutes** (a 13Z cycle).
- Rounded down to the nearest 5 minutes: **60 minutes**.

**PROPOSED_PUBLICATION_LAG_FLOOR_MINUTES = 60** (3,600,000,000,000 ns).

This is a floor on the *minimum possible* lag, not a typical or expected
lag — it is deliberately conservative: `available_at = max(S3 LastModified,
cycle + floor)` per plan §3.2 item 1, so a floor below every observed
live-relevant v5.0 lag can only make `available_at` MORE conservative
(later) than necessary on a day when the true `LastModified` already clears
it, never less conservative. The measured v5.0 13Z/19Z/01Z minimum (61.05
min) sits barely above the proposed 60-minute floor, which is the intended,
narrow margin: tight enough to reflect the real minimum-observed latency,
never rounded up past an actually-observed value.

## Caveats

- This is a **listing-only** census (no NBP bulletin bodies fetched, per the
  brief) — it establishes the floor from the object's S3 metadata, not from
  parsing bulletin content. SL-1b consumes this note's floor value directly.
- The sample is discrete dates, not exhaustive daily coverage; the two
  flagged late-publication events (2026-09-24, 2023-01-20) show that
  same-day lag has a long right tail on some days. The floor is a MINIMUM
  bound and is unaffected by that tail by construction.
