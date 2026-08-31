# EVIDENCE ONLY - NEVER INGEST

Every file in this directory is a read-only probe capture. It must **NEVER**
be ingested into any production catalog under any circumstance. Backfilling
these payloads under a plausible retrieval timestamp would be backdating, and
would destroy the point-in-time property the forecast design depends on.

Payloads carry the `.probe.json` suffix, which no production loader reads.
`request_manifest.tsv` records every request this probe dispatched, including
the ones that failed.
