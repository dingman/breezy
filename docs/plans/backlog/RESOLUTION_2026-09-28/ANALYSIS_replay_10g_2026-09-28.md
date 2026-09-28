# ANALYSIS — replay-daily 10G peak, 2026-09-28 15:50Z (AUD-10b)

Author: Claude performance-optimizer (read-only). Codex fell back: credit exhausted, `has_credits:false`, at 17:43Z. Merged by the coordinator.

## Findings
- The journal line reads: `7min 48.808s CPU over 7min 42.453s wall, 10G memory peak`, exit 0. CPU/wall is about 1.01, so this was **not** an L-49/L-53 reclaim stall; the run did real work.
- The census line reads: `census_provenance: run=2026-09-28 instances=66 cache=on hit=50 rescanned=5 cold=11`. So **16 of 66 instances missed the cache and needed conversion.**
  - `rescan_due` is a duplicate print of `rescanned` (`replay_sufficiency_census.py:1192`), not a distinct counter.
- f205349 (REPLAY-BIGINST) rewrote only span discovery, which is now column-projected and O(batch).
  - **Conversion was out of scope.** That covers `_convert_live_capture`, `read_feather_coalesced` whole-file reads, and the `_extend_overlapping_stream` EXTEND fallback with its unfiltered dedupe.
  - The r1 assumption that "conversion builds no objects" was never measured, because Stage 0 was never run.
- **Most likely consumer: conversion of the 16 cache-miss instances.** This is the same unbounded-conversion family as ING-2-AMEND2.
- Anonymous memory vs. page cache cannot be split after the fact: the cgroup is gone and only `memory.peak` was logged.

## Owed before the TEMPORARY 10G/12G drop-in comes off
1. **Stage 0:** `systemd-run --user -p MemoryHigh=3G -p MemoryMax=4G -p LimitNOFILE=524288`, running `_convert_live_capture` alone on the largest pinned cold instance.
   - Record `memory.peak`, `memory.stat` anon, wall, CPU/wall, the largest feather size, and whether EXTEND fired.
   - PASS: peak <2.5G, ≥25% headroom, CPU/wall >0.3, and no EXTEND.
2. **R3-5**, only after Stage 0 passes: a pinned hardlinked snapshot, OLD code (pre-f205349 detached worktree) at 10G/12G vs NEW code at 3G/4G, both with `--no-instance-spans-cache` and isolated outputs. Run a firewall-safe diff that reports keys only.
3. **Window:** 02:00–08:00Z, serialized through `breezy-studies.lock`. It must end before the 09:00Z rotation and 09:45Z ingest.

## Coordinator note
Stage 0's outcome depends on the ING-2-AMEND2 conversion fix. If that fix bounds conversion or EXTEND, Stage 0 should run on the fixed code.
