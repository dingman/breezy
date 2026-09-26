# ING-2: bounded quote-tape ingest (2026-09-25)

- **S1, definitions-first.** DELIVERED (merge c5d1e24, T3b fix c7d2b85). See `ING-2_S1_plan_r4_DELIVERED.md`.
- **S2, per-run deadline.** DELIVERED. See `ING-2_S2_plan_r3_amendment.md`.
- **S3, bounded memory.** Split into S3a (coalesced read, unconditional) and S3b (chunked EXTEND, conditional). See `ING-2_S3_plan_r2_2026-09-26.md` (r3/r3.1 amendments).
  - **S3a: MERGED (2026-09-26).** `breezy.persistence.feather_read.read_feather_coalesced` replaces `ParquetDataCatalog._read_feather_file`'s `reader.read_all()` on the fast path (`_convert_stream_natively`), the per-file path, the EXTEND read, and salvage collect. Measured on the real F3 file (891,170-message `instrument_status`, 698 MB): native `read_all()` peaks ~5.87 GB; the coalesced read's ΔRSS is ~164 MiB. The A8 write-mismatch detector (`ExtendWriteMismatch`) turns `write_data`'s silent exists-skip into a loud, reason-coded `failed` on the EXTEND path.
    - **Bounded after S3a:** the fast path and the per-file path.
    - **Still unbounded after S3a:** EXTEND (`_extend_overlapping_stream`, the per-file EXTEND fallback) still materializes a whole file's rows as objects and runs an unfiltered dedupe query (RS-3).
    - **Residual RS-4 (not covered by S3a):** native `_convert_feather_table_to_parquet`'s own same-directory, same-filename exists-skip (`parquet.py:2683-2685`) is indistinguishable from a successful write; a foreign file with an identical `(start, end)` filename would silently swallow rows. Closing it needs its own plan (a pre-write existence check or a post-write footer check on the native path).
  - **S3b (chunked EXTEND): see the Phase 0 findings for the trigger outcome (T-a/T-b) before scheduling.** If triggered, it is queued as the next ING-2 item in this README and `docs/core/PROGRESS.md`; otherwise it stays PARKED with the arm 3a numbers.

That r1 plan was reviewed REQUEST_CHANGES. The architect's slicing is binding:
- S2 keeps the unit at 4G/6G, adds `OOMScoreAdjust`, and sets the deadline at 600–720s rather than 1500s.
- S3 lands only after Stage 0 shows which of F3 and F4 dominates.
- The deadline is checked only between (instance, type) units, and one native unit can overrun it. Name that as a residual risk.
- The timers need no flock, because systemd runs one instance of a unit at a time.

Each slice needs a fresh plan and peer review before it is implemented.
