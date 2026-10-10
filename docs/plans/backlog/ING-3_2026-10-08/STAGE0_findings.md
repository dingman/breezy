# ING-3 Stage 0 findings (offline measurement, 2026-10-09)

**Plan:** `ING-3_plan_r2.md` §Stage 0 (S0.1–S0.7) plus convergence amendments C1–C4. No repo code was changed. The node, supervisor, recorder and `breezy-quote-tape-ingest` unit were never touched.

## Setup actually used
- **T_rot = 09:00:00Z.** The `breezy-quote-tape-rotate` timer fires at 09:00:00 and the recorder restart is done at 09:00:10Z (journal). The new instance is `2bb7b0d5`; the rotated, now-dead instance is `690b15b6`.
- **The production ingest fires on 15-minute boundaries, including 09:00:00, concurrently with the rotation.** The 09:00 run exits at ~09:00:29. The first *post-rotation* fire is therefore 09:15.
- **Snapshot root:** `~/.cache/breezy-ing3-s0/2026-10-09/`, same filesystem as the catalog (`stat -f` fsid equal). Every driver run asserted `catalog_root` is under `~/.cache/breezy-ing3-s0/`.
- **T1 = 08:46:01–08:46:09Z.** It ran after the 08:45 production run exited and before rotation. It hardlinked 58,770 dead-instance `*.feather` and `data/**/*.parquet` files and copied 9,247 dotfiles/other files. The live instance's dotfiles were copied, but its feather files were not taken.
- **T2 = 09:00:29–09:00:38Z.** It ran after the 09:00 production run exited and before the 09:15 fire. It refreshed all dotfiles, hardlinked the rotated instance's feather tree (59,451 links in total), and copied the new live instance with `cp2` (`shutil.copy2`, mtimes preserved).
- **Inode manifest:** 59,451 entries `(path, inode, size, mtime_ns)`. It was re-checked before and after every run, and again at the end. 0 changed and 0 missing, so **no ABORT**.
- **Runs:** each one was `systemd-run --user --wait --collect` with MemoryMax=14G (High 90%) or 2G (High 90%), `LimitNOFILE=524288`, `RuntimeMaxSec=780`, `TimeoutStartSec=780`, `Nice=10`, `IOSchedulingClass=best-effort/7`, `UMask=0077` and `OOMScoreAdjust=500`.
  - CPUQuota is infinity and IOWeight is unset on the production unit, so neither was passed.
  - A 1 s sidecar logged cgroup `memory.peak`, `memory.stat` (anon, file, file_dirty) and `memory.events`. RSS was never used.
- **Driver** = `run_ingest(root, now_ns=<sim t>, service_active_probe=lambda: True, convert_fn=default_convert, deadline=RunDeadline(budget_ns=600e9))`, constructed right before the call.
  - Simulated fire times: A = 09:15Z, B = 09:30Z, D = 09:45Z (T_rot + 45 min).
  - D reuses A1's output state. Before each run the snapshot was restored (dotfiles from a pristine copy, non-manifest files deleted).
  - Timing wrappers on core functions are transparent.
- **Coordination:** the marker `~/.cache/ING3_STAGE0_RUN_ACTIVE` was held during runs. Runs waited for `breezy-gate*`, study, replay, scorer and ingest services and for pytest (read-only `pgrep`).
  - Waits ran from 09:30 to 13:31Z, and again 14:50–15:25Z and 15:25–17:15Z (including the 16:30–17:10 hole).
  - No overlap with a running pytest or gate was recorded in any run (`wait_notes` in the raw JSON).
- **Wasted time:** the first scheduler version matched `.timer` units in its heavy-job glob, so runs did not start until 12:19Z. That was a scheduler bug, not a safety event. It was fixed to match only `.service` units.

## Census (S0.3), snapshot after T2
- **Instances:** 78. The 43 without a memo are mostly dead instances older than the memo; the new live instance is copied and has none.
- **Markers (first pass):** per-type `converted` 796, `converted-file` 2,243, `.salvaged-tc-temp-*` 6,088, `attempt` 3, `salvaged` 4, `salvage` 1.
- **Largest single feather:** `instrument_status` 1,733,331,848 B / 2,216,144 rows (`f90a3a0c`, EOS-closed).
  - Largest in the typed trees: `tc-temp-mdwhigh-2026-10-07` 890,143,608 B / 222,535 rows.
- **Largest TRUNCATED feather:** `instrument_status` 486,006,712 B / 621,428 rows (`887d2005`).
  - Largest truncated in the typed trees: 125,851,608 B / 31,462 rows.
- **Typed trees, dead instances, by state (files, bytes):**

  | Type | State | Files | Bytes |
  |---|---|---|---|
  | `order_book_depths` | INTACT+EOS | 1,891 | 89.9 GB |
  | `order_book_depths` | INTACT (no EOS) | 169 | 3.55 GB |
  | `order_book_depths` | TRUNCATED | 13 | 0.42 GB |
  | `custom_depth_truncation` | INTACT+EOS | 1,735 | 11.6 GB |
  | `custom_depth_truncation` | INTACT (no EOS) | 227 | 0.84 GB |
  | `custom_depth_truncation` | TRUNCATED | 5 | 20 MB |
  | `quote_tick` | INTACT+EOS | 1,774 | 14.3 GB |
  | `quote_tick` | INTACT (no EOS) | 168 | 0.56 GB |
  | `quote_tick` | TRUNCATED | 2 | 9 MB |
  | `trade_tick` | INTACT+EOS | 1,270 | 72 MB |

  The remaining types are small.
- **Data catalog layout (flat parquet at the type root vs deep):**

  | Type | Flat | Deep |
  |---|---|---|
  | `binary_option` | 7 | 5,268 |
  | `instrument_status` | 79 | 240 |
  | `custom_venue_clock_offset` | 82 | 0 |

  All other types are deep only.
- **`instrument_status` / definition row counts** (from the preflight memos): `instrument_status` 43.5M, `binary_option` 140,908, `custom_venue_clock_offset` 209,335, `instrument_close` 0.
- **Not collected:** DepthTruncation `instrument_id` metadata. I did not read feather schema metadata, to keep the snapshot read-only and cheap.
- **Caveat:** `census.py` was edited twice during the run. Its marker counters are from the first pass; the per-type breakdown is from the last pass.
- Raw census JSON: `scratchpad/ing3s0/census.json`.

## Raw numbers (S0.4)

Columns:
- `wall` = driver wall in seconds.
- `anon` = peak anon bytes in GB (sidecar, 1 s).
- `cg peak` = systemd "Memory peak" (sidecar max, GB).
- `file` = peak file cache in GB.
- `high` = `memory.events` `high` count.
- `def U/I` = deferred units / deferred instances.
- `adm` = `deadline.admitted`.
- "already exists" prints: 0 in every run.

| Run | Mem | Start (Z) | wall | anon | cg peak | file | dirty MB | oom_kill | high | def U/I | adm | EXTEND chunks (filtered/unfiltered) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | 14G | 13:31:43 | 14.1 | 0.294 | 1.4G (1.57) | 1.27 | 0.7 | 0 | 0 | 0/0 | 1 | 0 |
| A2 | 2G | 17:15:46 | 15.8 | 0.228 | 1.4G (1.53) | 1.29 | 0.4 | 0 | 0 | 0/0 | 1 | 0 |
| B (09:30 sim) | 14G | 19:31:16 | 6.8 | 0.153 | 443M (0.47) | 0.31 | 0 | 0 | 0 | 0/0 | 0 | 0 |
| C-a (no deadline, A) | 14G | 19:46:13 | 16.0 | 0.274 | 1.3G (1.49) | 1.18 | 0.4 | 0 | 0 | 0/0 | n/a | 0 |
| **D** | 14G | 14:15:47 | **594.5** | **1.773** | 4.6G (4.95) | 3.60 | 40.9 | 0 | 0 | 0/0 | 11 | 338/0 |
| C-d (no deadline, D) | 14G | 19:31:27 | **622.5** | 1.584 | 4.9G (5.31) | 3.99 | 40.7 | 0 | 0 | n/a | n/a | 338/0 |
| D | 2G | 15:00:39 | 593.9 | 1.525 | 1.8G (1.94) | 1.01 | 40.7 | 0 | 15,506 | 0/0 | 11 | 338/0 |
| D′ | 14G | 14:45:45 | 580.9 | 1.517 | 4.5G (4.85) | 3.53 | 38.7 | 0 | 0 | 0/0 | 10 | 261/0 |
| D′ | 2G | 15:15:46 | 574.4 | 1.629 | 1.8G (1.94) | 0.94 | 28.8 | 0 | 15,957 | 0/0 | 10 | 261/0 |
| A4 no-op (after D) | 14G | 14:30:43 | 4.8 | 0.157 | 160M (0.17) | 0.01 | 0 | 0 | 0 | 0/0 | 0 | 0 |
| **A3-i** (unclosed only) | 14G | 14:30:52 | **569.8** | 0.866 | 4.4G (4.83) | 3.98 | 38.1 | 0 | 0 | 0/0 | 10 | 259/0 |
| **A3-i** | 2G | 19:15:46 | **566.5** | 0.909 | 1.8G (1.94) | 1.67 | 30.6 | 0 | 17,108 | 0/0 | 10 | 259/0 |
| A3-ii (forced whole, A) | 14G | 19:46:33 | **656.3** | n/a | 5.8G (driver `memory.peak`) | n/a | n/a | 0 (driver `memory.events`) | 0 | **4/44** | 28 | 400/0 |

A3-ii caveat: its scheduler was stopped (SIGTERM from `systemctl stop` to the orchestrator unit) during its first seconds. The transient unit ran to completion on its own. The sidecar and runner result are missing, so the anon peak is not available. The wall, deferral counts, driver-side cgroup peak and `oom_kill=0` are from the driver. The manifest was re-checked afterwards: 0 changed.

Runs not performed: A3-iii (salvage only), A3-iv (definitions only), and A3-ii at 2G. Of the planned A3 isolations only A3-i (both sizes) and A3-ii (14G) were run. Time was lost to concurrent gates (see Setup). H3 and H6 are sized from per-unit timings in the A and D runs instead (below).

### Per-unit durations (driver timers, seconds)
- **A (in grace, 14 s):**
  - `scan_instance_memoized` 8.1 s over 35 scans (57%). 7.0 s of that is one scan of `690b15b6`.
  - `salvage_truncated_instance` 1.7 s over 5 calls (12%).
  - `_convert_one_definition_type` ~0 s.
  - The rotated instance `690b15b6` is `skipped-live`: its `binary_option` file is within grace, so every tick type reports `skipped-definitions-pending`. **No tick conversion happens in A.**
- **D (post-grace, 594.5 s):**
  - One `ingest_instance` unit for `690b15b6` takes **587.5 s** (99%).
    - `_extend_overlapping_stream` 523 s over 3 calls (381 s + 101 s + 41 s).
    - `_extend_table_chunked` 189 s over 299 calls.
    - `_convert_stream_natively` 57.5 s.
    - `convert_instrument_definitions` 6.5 s (1.1%).
  - Scans total 2.4 s (0.4%).
  - Salvage ~0 s.
  - The 587 s unit was admitted at t=3.3 s. `deadline.admitted` was 11 and nothing was deferred. The run finished 5.5 s under the 600 s budget.
- **A3-i (per-file, definitions unblocked):** 559 s for `_ingest_instance_per_file` on `690b15b6`.
  - `_convert_one_tick_type_per_file` 381 s + 95 s + 40 s + 40 s.
  - `_extend_table_chunked` 183 s over 220 calls.
- **D′ (forced per-file):** 574.5 s for `690b15b6`.
  - `_extend_table_chunked` 181 s.
  - `convert_instrument_definitions` 6.8 s.

### What the numbers say
1. **B and C-a:** A runs in ~15 s, and so does B (09:30 sim) because grace has not expired. The heavy work on `690b15b6` is deferred by the open-definitions rule until grace expires, then lands in the first fire after rotation+30 min, which is the 09:45 fire (D).
2. **D, in production terms:** 595 s (or 623 s with no deadline) for one instance. This matches the 606–705 s failures in the plan.
3. **A3-ii (14G):** forcing the whole-instance path in A reproduces the full failure signature: wall 656 s, 4 deferred units, 44 deferred instances.
4. **D vs D′ (CR-4 test):** D′ is no worse than D on wall (580.9 vs 594.5 s at 14G; 574.4 vs 593.9 s at 2G) or anon (1.52 vs 1.77 GB; 1.63 vs 1.53 GB at 2G, within noise). The other dead instances (7 s total) took no longer on the per-file path.
5. **Where the time goes:** both paths spend ~570–590 s in the EXTEND dedupe/chunk machinery for `690b15b6`'s `quote_tick`, `order_book_depths` and `custom_depth_truncation` types. EXTEND is entered from native non-disjoint refusal in D and from per-file in D′. The per-file vs whole-type choice changes wall by 2%.
6. **Page cache:** at 14G, file cache is 73% of `memory.peak` in D (3.6 of 4.95 GB). anon peak is 1.5–1.8 GB at both 14G and 2G.
7. **2G runs:** all pass, `oom_kill=0`, with ~15–17k `memory.high` throttle events and unchanged wall time. The cgroup peak sits at the 1.8G MemoryHigh line.

## Build-gate decisions (S0.6)
The rule is "build W1/W2/W4/W5 only if the hypothesis carries ≥15% of anon peak or wall; W3 is exempt".

| Package | Hypothesis | Measured carry | Decision |
|---|---|---|---|
| **W1** | H2 (post-grace re-read, re-extend) | D vs D′ differential: −2.3% wall, −14% anon (14G) / +7% anon (2G). Neither reaches 15%. | **Not gated in.** CR-4 test passes if W1 is built later: D′ is no worse than D, so every non-truncated dead instance goes per-file. |
| **W2** | H5 (deadline granularity) | Deferred 0/0 in D, D′, C-d and A. A3-ii deferred 4/44, but only when forced onto the whole-instance path. Largest single unit is 587 s (99% of wall). | **Not gated in by this data.** Flag: D finished 5.5 s under budget, so a slightly slower host would overrun. C1 pending-check is moot unless A3-ii-like state recurs. |
| **W3** | H3 (salvage unbounded) | Salvage 1.7 s / 12% of A wall; ~0 s in D; anon in A 0.29 GB. Largest truncated file 486 MB / 621k rows. | **Exempt (correctness fix, N4).** The size data does not argue for urgency. |
| **W4** | H6 (definitions all-time query) | 6.5 s of 594 s (1.1%). | **Not gated in.** |
| **W5** | H4 (page cache, memo rescans) | A2: file 1.29 GB vs anon 0.23 GB, so cache dominates `memory.peak` (84%). D: 73%. Memo scans are 8.1 s (57%) of the 14 s A run, but 0.4% of D. | **Literal rule met in variant A only.** It affects no pass/fail, because anon already passes. |
| Native streaming dedupe | N2 | Dedupe queries carry the bulk of the wall: `_extend_table_chunked` 181–189 s of 570–594 s (32%), plus the overlapping-stream machinery around it. Anon share of dedupe queries not isolated. | **Revisit.** The 15% wall threshold is met. The anon share needs a profile (peak-memory attribution per chunk) that this run could not do. |

## STOP evaluation (S0.7, C2)
- **Time STOP: FIRES.**
  - A3-i is 569.8 s at 14G and 566.5 s at 2G, both above ~450 s.
  - D is 594.5 s (623 s with no deadline) for a single unit that the deadline cannot interrupt.
  - A3-ii reproduces the production deferral signature (656 s, 4 units/44 instances deferred).
- **Memory acceptance (anon ≤2G and `oom_kill=0`): PASS in every run I measured.**
  - Max anon peak is 1.773 GB (D, 14G), and 1.63 GB at 2G.
  - `oom_kill=0` everywhere. A3-ii has no anon peak (sidecar lost) but `oom_kill=0` from the driver's `memory.events`.
  - By S0.7, memory acceptance alone gates drop-in removal. It is not removed by this task.
  - Caveats:
    - The runs were alone on the host, apart from other agents' gates, with no node load competing for I/O.
    - The unit's own limits (4G/6G) were not tested; 2G throttles heavily (MemoryHigh=1.8G).
- **C2 branch (c):** the second clause ("no hypothesis carries ≥15%") is met. Every package-level differential is under 15% (W1: 2–14%, W2: 0, W4: 1%).
  - The dominant consumer is EXTEND/dedupe on the rotated instance's `quote_tick`, `order_book_depths` and `custom_depth_truncation` types, ~570 s regardless of path.
  - Branch (c) as written (drop-in stays, relabelled TEMPORARY with a date, r3 targets that consumer) is recorded here. The memory leg of C2 (anon above 2G) is **not** met.
- **Pre-declared post-STOP branches (not chosen here; the coordinator's peer loop chooses):**
  - **(a) Bounded multi-run drain:** `deferred_units` > 0 only for pending work, and the backlog drains within N ≤ 3 runs (< `STALL_MIN_CONSECUTIVE_RUNS=4`).
    - Data point: D shows one unit that cannot be split below type level. The largest sub-unit is `quote_tick` at ~381 s.
  - **(b) Native rotation lever:** shorten `QUOTE_TAPE_ROTATION_INTERVAL` (`node_config.py:446-448`). It needs a recorder restart and a separate peer-reviewed plan.
  - **(c) per C2.**

## Safety record
- Manifest: 59,451 entries; 0 changed, 0 missing, at start and end. No ABORT.
- Hardlinks were made only for dead-instance non-dot `*.feather` and `data/**/*.parquet`. Dotfiles and the live instance were copied. No chmod was done on any link.
- The only production-adjacent action was reading. No signal, restart or touch of the node, supervisor, recorder or ingest unit.
- One orchestrator restart killed a not-yet-started runner (twice, with no run in flight) and orphaned A3-ii (see above).

## Status
Stage 0 is incomplete relative to the plan table. A3-iii, A3-iv and A3-ii at 2G were not run; the time and memory STOP conclusions do not depend on them. The snapshot was removed after this commit.

## Post-STOP ruling (coordinator, 2026-10-09, peer loop)

Peers consulted: trading-bot-architect (branch choice) and performance-optimizer (hotspot).

**Ruling.** S0.7's memory leg governs. C2(c) does not apply, because its "no hypothesis ≥15%" clause is a time criterion. On that basis:
- The TEMPORARY memory drop-in was **removed 2026-10-09 20:00:51Z** using the r2 removal procedure and the C4 amendments. The backup is at `~/.cache/breezy-ing3-s0/dropin.bak`.
- An auto-rollback watch (`breezy-ing3-postremoval-watch.timer`) restores the drop-in on oom_kill or a non-zero exit.
- The post-removal runs 20:00–21:15Z all exited 0 with no oom.

**Branches (b) and (c) are parked.** They reopen if any one of these trips:
- wall time > 700 s;
- `DEFERRAL_STALLED`;
- a timeout kill.

**Correction to the architect's reasoning.** `RunDeadline.admit` is a start-gate only, so a 1.15× slowdown does NOT defer the last unit. It admits all three units and overshoots the 600 s budget, to about 601 s. Deferral needs a slowdown of at least ~1.245×. This is pinned by `tests/unit/test_quote_tape_ingest_deferral_pin.py` (merge 585d8f7e).

**Residual risk (for r3).** Worst-case wall is the budget plus the largest unit, about 600 + 381·k s. That exceeds `TimeoutStartSec=780` if quote_tick is admitted late in a run. The failure mode is a timeout kill: OnFailure fires an alert, and the next run converts the remaining types, because conversion is idempotent and per-type marked. The fix candidate is a size-aware admit.

**Perf notes.**
- About 64% of the 523 s is in `read_feather_coalesced` and `_list_feather_data_files`, which are not yet timed. Dedupe is already filtered.
- `consolidate_data` is unusable on this non-disjoint layout.
- Options, ranked: profile those two first; then per-type process parallelism (~27%); then a landed-watermark fast path, which is high risk.

**ING-3 closes** only after the first post-removal 09:45Z-class run on 2026-10-10 is verified: exit 0, oom_kill 0, wall < 700 s.

## Close-out (2026-10-10)

The first post-rotation run without the drop-in was the **09:45Z fire**. It exited 0 after 627 s wall, below the 700 s tripwire. It deferred 4 units across 63 instances; `rss_peak_mb` was 1872 and systemd's memory peak was 4G, at MemoryHigh including page cache. There was no oom.

The **10:00Z fire drained the backlog**: deferred 0, 143 s, `rss_peak_mb` 994. This is branch (a) behaviour, a one-run drain, which is well within `STALL_MIN_CONSECUTIVE_RUNS=4`.

Every run from 20:00Z 10-09 through 10:00Z 10-10 exited 0 with no oom. The auto-rollback watch timer was stopped at 10:1xZ. **ING-3 CLOSED.**

The residual risk carries forward: a timeout kill if a large unit is admitted late (600 + 381·k s against a 780 s limit).
