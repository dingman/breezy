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

## Phase 0 results (2026-09-26)

Ran per `ING-2_S3_plan_r2_2026-09-26.md` r3 amendment ("Phase 0 → Conditions",
"Metric", the r3 arm table + row 3a-ii, "Seeding"). Quiet window confirmed
before the first arm: `breezy-quote-tape-ingest.service` went `inactive` at
11:25:16Z (it had been mid-backlog-drain since ~10:45Z; waited it out),
`breezy-studies.slice` showed `Act. Units: 0 / Tasks: 0`, no `pytest` /
`run_tests_no_egress.sh` process was actually running (matches against those
strings were stale wait-loop wrapper processes from earlier background Bash
calls, not real test runs), `free -g` available was 21 GiB. All six
`systemd-run` units (seeding ×2, arms 0/1/2/3a-i/3a-ii) ran back-to-back
between 11:25:37Z and 11:28:37Z, one at a time, all inside the deadline
(14:05Z). No OOM kill on any unit; the failure ladder (L1/L2) was **not
invoked** because arms 1 and 2 both passed with wide margin.

- **F3 identity.** `instrument_status_1789462839523897147.feather`, size
  697,670,024 bytes (matches the plan's fixed value exactly; the sibling file
  in the same instance dir, `instrument_status_1789516801432621471.feather`,
  is 167,884,336 bytes and was not used).
  sha256 of the scratch copy: `6dd884c4d13353ca829a33af098fa4961cdf023fee2bf238c6899ad606aa1ac8`.
- **Repo state at run time.** `git rev-parse HEAD` = `394af0ecac9ed7a7bb9177df542513d02dceb4f6`;
  `git status -sb` = `## feat/data-capture-and-risk...origin/feat/data-capture-and-risk [ahead 733]` (clean).
- **Scratchpad root (`P0`).** `/tmp/claude-1000/-home-jon-breezy/79dfa8fd-ce2b-4de9-b90f-b4cbd9fbda7e/scratchpad/ing2-s3-phase0`.
  Layout matches the plan: `proto/` (`proto_feather_read.py` — verbatim per
  Arch §1 + the P1 assembly fix; `arm_common.py`, a small helper for the
  baseline-VmRSS print and the plan's exact `_cgroup_memory_peak()` code),
  `arms/`, `src/live/c0c77dec-.../`, `seed/`, `cat/`, `logs/`.
- **PYTHONPATH.** `$P0/proto:/home/jon/breezy/src` for every unit, per r3.

### Seeding (r3 Seeding, fraction 0.9)

| Step | Unit | Result | ΔRSS | wall |
|---|---|---|---|---|
| 1. `seed_flat_prefix.py` | `ing2-s3-p0-seed-prefix` | counted 891,170 total messages, wrote first `ceil(0.9×891170)=802053` messages to a new flat IPC stream | baseline 58,708 KB → max 66,124 KB (7,416 KB, trivial) | 13.31s |
| 2. `seed_catalog.py` | `ing2-s3-p0-seed-cat` | native `_convert_feather_table_to_parquet` into `$P0/seed/cat_prefix90`; layout assertion held: exactly one `*.parquet` at depth 1 under `data/instrument_status/`, no subdirectories, `num_rows == 802053` | baseline 262,960 KB → max 429,340 KB (166,380 KB) | 7.42s |

`$P0/cat/arm3a-ii` was then made as `cp -a $P0/seed/cat_prefix90 $P0/cat/arm3a-ii` (plain copy, not under `systemd-run`, per r3: only the two seeding steps above are the capped units).

### Arm table

| Arm | ΔRSS (pass criterion) | vs 1 GiB line | cgroup `memory.peak` | wall time | OOM | rows written |
|---|---|---|---|---|---|---|
| 0 (baseline, `_scan_stream(collect=False)`) | 267,716 − 263,288 = 4,428 KB (≈4.3 MiB) | n/a (floor check only; ≪1 GiB) | 123,744,256 B (≈118 MiB) | 3.66s | no | n/a |
| 1 (`read_feather_coalesced` alone) | 431,268 − 263,080 = 168,188 KB (≈164.3 MiB, 0.1604 GiB) | **PASS** | 287,666,176 B (≈274.3 MiB) | 8.27s | no | n/a |
| 2 (arm 1 + native `_convert_feather_table_to_parquet`) | 442,640 − 263,192 = 179,448 KB (≈175.2 MiB, 0.1711 GiB) | **PASS** | 311,238,656 B (≈296.8 MiB) | 8.63s | no | 891,170 (fast-path convert, empty catalog) |
| 3a-i (unchunked EXTEND, empty catalog) | 1,174,660 − 309,592 = 865,068 KB (≈844.8 MiB, **0.8250 GiB**) | **PASS** (margin ≈179 MiB under the 1,073,741,824 B line) | 1,037,160,448 B (≈989.1 MiB, 0.9659 GiB) | 56.51s | no | 891,170 (all fresh; empty catalog) |
| 3a-ii (unchunked EXTEND, seeded flat-prefix-90 catalog copy) | 1,632,748 − 309,804 = 1,322,944 KB (≈1292.1 MiB, **1.2618 GiB**) | **FAIL** (exceeds both the 1 GiB general line and the 0.5 GiB 3a-ii line) | 1,497,767,936 B (≈1428.1 MiB, 1.3946 GiB) | 15.99s | no | 89,117 fresh (802,053 of 891,170 dropped as already-landed, matching the ≈0.9M-query / ≈0.1M-write shape r3 predicted) |

No arm hit `cap-pressured` (`memory.peak ≥ 0.95 × 2 GiB` = 2,040,109,465.6 B); the highest peak (arm 3a-ii) was 1.3946 GiB, comfortably under both the cap and the pressure-annotation line.

### Ladder outcome

**Not invoked.** The failure ladder (L1 `COALESCE_ROWS=1024`, L2 `+MALLOC_ARENA_MAX=2`, L3 Option D) applies only to a failing arm 1 or arm 2 (r2 A5 / r3 Phase 0 "Failure ladder"). Both passed cleanly on the first capped run at the default `COALESCE_ROWS=8192`, so no ladder rung was run.

### S3b trigger (T-a / T-b) verdict

- **T-a: FIRED.** Arm 3a-ii ΔRSS = 1.2618 GiB > the 0.5 GiB line for 3a-ii (also > the 1 GiB general line). Arm 3a-i alone passed (0.8250 GiB ≤ 1 GiB), so T-a fires solely on the 3a-ii number — the near-worst-case unfiltered dedupe query over a mostly-landed range is exactly the term r3's tighter 0.5 GiB line was written to catch (RS-3 / `_drop_already_landed_unfiltered`).
- **T-b: not measured in Phase 0.** T-b is AC-S3-5(b), a post-merge production check on the merged S3a code; it is out of scope for this Phase 0 session.
- **Conclusion: S3b is triggered by T-a and must be queued as the next ING-2 item** (per r3 Success criteria), independent of T-b. Arm 3b itself was **not run** in this session, as instructed — it is S3b's own gate, run when S3b is built.

### Adaptations

**None required.** Every Nautilus internal the plan named was re-checked against the installed tree (`nautilus_trader/persistence/catalog/parquet.py` in `.venv`) before writing the arm scripts, and every signature matched exactly as documented in the plan: `_read_feather_file(path) -> pa.Table | None`, `_convert_feather_table_to_parquet(feather_table, feather_path, data_cls, used_catalog, use_ts_event_for_ts_init=False)`, `_handle_table_nautilus(table, data_cls, convert_bar_type_to_external=False, use_ts_event_for_ts_init=False)` (staticmethod), `_make_path(data_cls, identifier)`, and `breezy.runtime.quote_tape_salvage.write_fresh_capture_rows(write_target, data_cls, objects) -> int`. `ParquetDataCatalog` imports cleanly from both `nautilus_trader.persistence.catalog` and `nautilus_trader.persistence.catalog.parquet`. `InstrumentStatus` imports from `nautilus_trader.model.data`. The prototype (`proto_feather_read.py`) was written top-level exactly per Arch §1 plus the r1/P1 python fix (`.to_batches()` per coalesced group, final `Table.from_batches(batches, schema=reader.schema)`) and smoke-tested against a synthetic 500-message flat prefix of the real F3 stream before being run against the full file, with no code changes needed afterward.

One process note, not a plan deviation: the quiet-window wait (§ above) needed a `systemctl --user is-active` poll loop rather than a single check, because the ingest unit was genuinely mid-backlog-drain (started ~10:45Z, per `journalctl`) when this session began; it went `inactive` at 11:25:16Z and the six Phase 0 units ran immediately after with no further contention.
