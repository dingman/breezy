# Venue rules evidence — Polymarket US

This directory holds immutable, verbatim snapshots of third-party venue rules text — the
published documentation that governs how Breezy's weather contracts settle. Venue rules can
change silently between two nominally identical daily markets, so each capture is stored
exactly as retrieved, with no summarising, paraphrasing, reformatting, or editorial cleanup.
The captured bytes are the evidence; anything less than verbatim is worthless for settlement
reconciliation.

Files here are **append-only**. Never edit a capture in place and never overwrite one. Each
retrieval produces a new dated file (`<page>_<YYYY-MM-DD>.md`) alongside its own
`<page>_<YYYY-MM-DD>.meta.json` sidecar recording the source `url`, the `retrieved_at` UTC
timestamp, the `sha256` digest of the capture, who captured it, and a one-line note. A
correction or a re-fetch is a new dated pair, not a modification of an existing one — the
diff between two dated captures is precisely the signal we are retaining.

The digests exist so that a later reader — reconciling a disputed settlement, or auditing a
trade months after the fact — can prove the text has not been altered since capture. Verify
any file with `sha256sum -c` against the digest in its sidecar, or directly:
`sha256sum <capture-file>` and compare to the `sha256` field. A mismatch means the artifact
has been tampered with or corrupted and must not be relied on as evidence.

Note on capture form: `weather-faqs_2026-08-22.md` is the byte-exact response body served by
the venue's own Markdown endpoint (`<page-url>.md`), which includes a short server-injected
"Documentation Index" preamble ahead of the page content. That preamble is retained
deliberately — stripping it would alter the bytes the digest attests to.
