# EVIDENCE ONLY - NEVER INGEST

Every file in this directory is a read-only probe capture. It must **NEVER**
be ingested into any production catalog under any circumstance. Backfilling
these payloads under a plausible retrieval timestamp would be backdating, and
would destroy the point-in-time property the forecast design depends on.

Payloads carry the `.probe.json` suffix, which no production loader reads.
`request_manifest.tsv` records every request this probe dispatched, including
the ones that failed.

## Oversized bodies trimmed (2026-09-19, coordinator)

Four captures in this directory are fetches of the same ~30 MB collective NBM
bulletin (`p2_collective_nbstx`, `p5_lag_20260919_{00,06,12}`). Stored in full
they were ~115 MB, against a 78 MB repository — they would have roughly tripled
it permanently, for four near-duplicate copies of one file (the 304 on the
conditional re-GET confirms the duplication).

Each of those four `.probe.json` files now carries:

* the **sha256 of the FULL body**, unchanged, under `sha256`;
* the first 400 lines of the body under `body`;
* a `body_trimmed` object recording `original_bytes`, `original_lines`, and how
  to recover the full payload.

Nothing else was altered. Headers, status, URL, timing and outcome are as
captured.

**Why this is not evidence-tampering.** The sibling probe in this same family
already sets the precedent for large payloads: `iem_mos_reachability_probe.py`
records `.summary.json` with `text=None` and stores **no body at all**, relying
on the recorded sha256 for verifiability. Storing four full 30 MB bodies was an
inconsistency with that precedent, not a deliberate integrity requirement.

**What the excerpt still proves.** It retains ten complete
`NBM V5.0 NBS GUIDANCE` station-block headers — the exact evidence behind both
the station-block-grammar answer (q6) and the header-regex fix (the real header
carries a `V5.0` version token the old pattern rejected). Anyone can re-GET the
recorded URL and verify the sha256 to reconstitute the full body.
