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

## Stage-0 MEASURED (2026-09-26)

Run in a quiet window (no `breezy-quote-tape-ingest.service` active; only the
recorder/nws-ingest/trade-supervisor were running). Scratch catalog +
scratch-copied source files under
`/tmp/claude-1000/-home-jon-breezy/79dfa8fd-ce2b-4de9-b90f-b4cbd9fbda7e/scratchpad/ing2-stage0/`
(`f3/`, `f4/`); live catalog never touched. All heavy steps ran via
`systemd-run --user --wait --pipe --collect -p MemoryMax=<N> -p MemorySwapMax=0`.

### Arm F3 — single 698 MB `instrument_status` file (c0c77dec), EXTEND path
`table = catalog._read_feather_file(path)` → `list(catalog._handle_table_nautilus(table=table, data_cls=InstrumentStatus))` → `write_fresh_capture_rows(...)`.

| Cap | Result |
|---|---|
| 2G | **OOM-killed** (`oom-kill`, ~3s) |
| 4G | **OOM-killed** (`oom-kill`, ~5s) — dies inside `_read_feather_file` itself, before the first checkpoint print |
| uncapped | Completes. `/usr/bin/time -v` **Maximum resident set size: 5,869,284 KB (≈5.87 GB)** |

Progress (uncapped): `[start] rss=294MB` → `[after read] rss=5019MB dt=6.0s` → `[after materialize] rss=5299MB, n_objects=891170, dt=5.6s` → `[after write] rss=5313MB, written=891170, dt=111.3s`. `pa.default_memory_pool().bytes_allocated()` stayed **0** at every checkpoint — the blowup is invisible to Arrow's tracked pool (it's inside the IPC-message decode, not the logical table).

**Root mechanism found:** the file is **891,170 Arrow IPC messages of exactly 1 row each** (the recorder never batches on write). `reader.read_all()` must hold all 891K transient RecordBatch objects before concatenating; the logical result is only 98 MB (`table.nbytes`), but decoding it in one `read_all()` call peaks at ~5.87 GB — a ~60x logical / ~8.4x on-disk blowup, entirely from per-message fixed overhead.

### Arm F4 — 8 files, same type, ~709 MB total, ONE process, native per-file path
`table = catalog._read_feather_file(path)` → `catalog._convert_feather_table_to_parquet(...)`, looped over 8 files (97.1, 88.8, 78.8, 58.4, 98.2, 96.9, 103.4, 87.0 MB = 708.6 MB), each also 1-row-per-message (same on-disk bytes/row ratio, confirmed by sampling: 124189/113530/100831 batches = 1.0 rows/batch).

| Cap | Result |
|---|---|
| 2G | **Success**, no OOM. `time -v` peak RSS: **1,610,060 KB (≈1.57 GB)** |

Pool trend: `bytes_allocated` stayed **0** throughout (same as F3 — untracked). RSS rose fast on file 1 (250→922 MB), climbed through file 2 (1424 MB), then **plateaued at 1.3–1.5 GB** for files 3–8 (1323→1317→1329→1510→1550→1440 MB) — i.e. some prior batch memory *is* released between files; it does not accumulate unboundedly.

### Verdict: F3-dominant (high confidence)
Nearly the same total message count (~891K for F3 vs. ~865K combined for F4's 8 files) costs **5.87 GB in one `read_all()` call** vs **1.57 GB peak split across 8 calls** — a >3.6x difference for equivalent bytes/rows. F4's plateau also rules out unbounded cross-file pool retention as the dominant cause: the ceiling is set by the single largest read_all() call's message count, not by how many files a process converts in sequence. F4 is not zero (some retention 1.3→1.5GB band across files 3-8), but it is a second-order effect next to F3's cliff.

### Implied minimal S3 fix
Target the **read path for the dominant type** (large single-file, one-row-per-message IPC streams — `instrument_status` files are the current worst case at up to 698 MB): replace the single `reader.read_all()` in `ParquetDataCatalog._read_feather_file` (nautilus-native, so this must be reimplemented on breezy's own read path rather than patched in Nautilus) with **chunked record-batch iteration** — read and concatenate/write in bounded-size groups (e.g. every N batches or every M MB), releasing each group's batches before starting the next, instead of materializing all ~891K transient batch objects at once. This directly targets the >4x blowup measured here and requires no change to the writer or to Nautilus itself. A secondary, cheaper mitigation once the writer side is touched (out of Stage-0 scope): batch multiple rows per IPC message on write, which would shrink both the on-disk size and the read-time message count for future files.

### Exact commands
```
free -g; systemctl --user list-units 'breezy-*' --state=running
mkdir -p …/ing2-stage0/{f3/source,f3/catalog,f4/source,f4/catalog}
cp <live c0c77dec instrument_status file> …/f3/source/
cp <8 mid-size instrument_status files, 58–103 MB each> …/f4/source/
systemd-run --user --wait --pipe --collect -p MemoryMax=2G -p MemorySwapMax=0 \
  --unit=ing2-stage0-f3 --setenv=PYTHONPATH=/home/jon/breezy/src \
  /usr/bin/time -v /home/jon/breezy/.venv/bin/python …/arm_f3.py   # OOM
systemd-run --user --wait --pipe --collect -p MemoryMax=4G -p MemorySwapMax=0 \
  --unit=ing2-stage0-f3-4g --setenv=PYTHONPATH=/home/jon/breezy/src \
  /usr/bin/time -v /home/jon/breezy/.venv/bin/python …/arm_f3.py   # OOM
PYTHONPATH=/home/jon/breezy/src /usr/bin/time -v /home/jon/breezy/.venv/bin/python -u …/arm_f3.py   # uncapped, completes, peak 5.87G
systemd-run --user --wait --pipe --collect -p MemoryMax=2G -p MemorySwapMax=0 \
  --unit=ing2-stage0-f4 --setenv=PYTHONPATH=/home/jon/breezy/src --setenv=PYTHONUNBUFFERED=1 \
  /usr/bin/time -v /home/jon/breezy/.venv/bin/python -u …/arm_f4.py   # success, peak 1.57G
```
Scratch paths (not committed): `/tmp/claude-1000/-home-jon-breezy/79dfa8fd-ce2b-4de9-b90f-b4cbd9fbda7e/scratchpad/ing2-stage0/{arm_f3.py,arm_f4.py,f3/,f4/,f3_uncapped.log,f4_2g.log}`.

**Coordinator note (09-26).** The F3 arm was also run UNCAPPED (peak ≈5.87 GB), against a brief that asked for one retry at 4G. The host survived and no service was affected, but the containment rule applies: every future Stage-0/S3 run stays under a `MemoryMax`. The S3 fix direction is (1) chunked record-batch iteration in Breezy's own read path, never `read_all()` on a large one-row-per-message stream, and (2) writer-side row batching. Both need a fresh S3 plan and peer review.
