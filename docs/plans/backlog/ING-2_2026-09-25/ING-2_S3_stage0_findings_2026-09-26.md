# ING-2 S3 Stage 0: findings from existing evidence (2026-09-26 ~05Z, read-only)

This file records what existing evidence shows. The protocol at the end has **not been run yet**.

## Journal, last 24 h
Every run of `breezy-quote-tape-ingest.service` finished with no OOM kill.

**Every run reports exactly `4G memory peak`**, which equals MemoryHigh. That held whether the run took 5 or 17 minutes, so the unit is being throttled at the ceiling.
- Steady state (21:00–02:00Z): runs took 5–6 minutes.
- Backlog episode (02:15–04:08Z): runs took 16–17 minutes, then drained back to 9 minutes by 04:29Z.
- One run (09-25 21:36Z) also hit a 134.6M swap peak.
- Host swap was 7.5/8 GiB used while AUD-07 M1c was running.

## Catalog (`live/` = 99G, 21,684 feathers, 62 instances)
The ten largest files are flat `instrument_status_*.feather` files of 486–698 MB. The largest is c0c77dec at 697,670,024 bytes.
- The largest per-instrument depth file is about 227 MB.
- Per-instance totals run up to 6.37G. For a6abd60e, `order_book_depths` alone is 4.2G.

## Code
- **F3: whole-file materialization.** Memory scales with the size of a single file. `_extend_overlapping_stream` (`quote_tape_ingest_cli.py:686-689`, read then `list(_handle_table_nautilus)`), the per-file path (`:1134`, `:1182-1183`), and `quote_tape_salvage._drop_already_landed_unfiltered` (`:154-156`). The last one queries every landed row in `[min, max]`, so its memory is unbounded by chunk size.
- **F4: retention of Arrow pool memory across files.** No code evidence either way, because there is no pool probe and no `release_unused` in the ingest path. Still unmeasured.

## Preliminary verdict
**F3 dominates, at MEDIUM-HIGH confidence.** The peak is flat regardless of backlog size, the worst-case single file is 698 MB, and F4 has no evidence behind it.

## Protocol still owed
Run this later in a quiet window, with no study running, on a scratch copy, never against the live catalog. Use one heavy job at a time.
1. **Arm F3:** convert the single 698 MB `instrument_status` file under `systemd-run --user -p MemoryMax=2G` and `/usr/bin/time -v`.
2. **Arm F4:** convert N small files with the same total bytes in one process, printing `pa.default_memory_pool().bytes_allocated()` after each file.
3. **Record:** max RSS, the pool trend (flat means F3; rising means F4), and whether either arm gets OOM-killed (exit 137).
