# Plan: make the replay-sufficiency census incremental (AUD-09b C6 hardening)

**Two premises in the brief are off, and they change the fix:**
- **Option (a) already exists.** It is AUD-09b C6 at `scripts/analysis/replay_sufficiency_census.py:303-314,371-386,440-441` and `src/breezy/analysis/instance_span_cache.py:98-107,156-283`. The production cache holds 55 instances (`~/.local/share/breezy/derived/replay/instance_spans.jsonl`). The fix is to harden C6, not to build it.
- **The census, not the runner, is what died on 09-27.** `replay_daily.log` has nothing after `2026-09-26T16:30:52Z replay daily ok` (line 26). The census prints its summary only when it finishes (census:681), and there is no SKIPPED line, so the lock was taken. 128→137 is the census's station-day row count (log lines 1 and 17), not a runner input count.

## 1. Where the per-run cost comes from
| Cost | Where | Scales with |
|---|---|---|
| **Full stream scan of every feather file of every instance**, every run, before the cache is consulted | census:509-510 → `scan_instance` (feather_preflight.py:539) → `_scan_stream` reads every message to EOF (:317-353) | **O(total corpus bytes)**. The `live/` backlog was 90G (LESSONS.md:1546). The page cache from this read is charged to the unit's cgroup (MemoryHigh=3G, service:36). |
| Feather→parquet conversion, cache misses only | census:388-394 → `default_convert` ×4 types (run_weather_strategy_backtests.py:1320-1321) | O(missed instances). A **whole-table** registry-offset fingerprint (census:294-300, folded in at :314) means any registry offset edit misses **every** instance. |
| Converted work catalog held on **tmpfs** until the process exits | work_root = `TemporaryDirectory` (census:667), per-instance dir (:388), never deleted per instance. `/proc/mounts`: `tmpfs /tmp`. | Grows with misses. tmpfs pages are shmem, charged to the cgroup. |
| Per-instance object high-water | `by_station_day` holds ALL days' `TapeInstrument`s at once (census:403-407). Each carries full depth/quote/close lists (backtests:1393-1410,1420-1426). | The largest instance, all of its days together. Not measured yet (Stage 0). |
| **A killed run keeps nothing** | The cache is written once, after the whole loop (census:535-536) | Once a cold run exceeds 1800s it never finishes on any later day. This is the L-49 zero-progress pattern (LESSONS.md:1546). |
| Small | LIVE/CORRUPT registrations read binary_option only (census:471, :538) | Few instances |

The sanctioned diagnosis (L-49, LESSONS.md:1552) matches: 12m CPU over 30m wall is 0.4 CPU/wall, at MemoryHigh.

**Trigger for 09-27: not established.** Candidates:
- (H1) scan page cache plus a larger corpus;
- (H2) a mass cache miss (registry offset edit, or feather mtime churn) filling tmpfs;
- (H3) one large new instance.

Stage 0 tells them apart.

## 2. Options
- **Nautilus null hypothesis:** Nautilus has no per-instance incremental summary. `convert_stream_to_data` silently skips filenames that already exist (parquet.py:2680, cited at backtests:1289-1292), so reusing a persistent work catalog would be a silent partial no-op. **Native does not cover this.** Breezy already has C6 and the preflight memo.
- **(a) Harden C6** (fingerprint → reuse rows). **PICK.** Output-neutral by construction: cache hits feed the same `classify_station_day` (census:246-255).
- **(b) Census only non-terminal days.** **REJECT.** It drops rows, which breaks `_assert_census_is_complete` (census:271-281) and changes WHAT the EDGE-4 counter sees (firewall). It is also impossible before conversion: an instance's station-days are unknown until it is converted (census:289-292).
- **(c) Reuse the live catalog's parquet.** **REJECT.**
  - The census does convert raw feather itself (census:389; `target=work`, backtests:1321).
  - But the merged catalog has lost instance provenance, and the census counts PER INSTANCE with a winner rule (census:31-35). Using it would change what is counted.
  - The 6b preflight memo is reusable for the scan only, and only **read-only**: `scan_instance_memoized` writes into the capture dir (preflight_memo.py:182,233), which is ingest's job.

## 3. The chosen design
1. **Skip the scan on a C6 hit.** Compute the stat-only fingerprint first. On a hit, classify as CLEAN without calling `scan_instance`.
   - Sound because CLEAN depends only on content, never on `now_ns` (cli_basis_offer_gate_scan.py:403-410), and only CLEAN is ever cached (instance_span_cache.py:162-168).
   - Residual: an edit that preserves size and mtime goes undetected. That is the existing, accepted A7 limit (test `test_a7_…`).
2. **Checkpoint the cache after each converted instance** with an atomic rewrite (instance_span_cache.py:171-188), not only at census:535-536.
3. **Fingerprint by the instance's own stations.** Each entry stores `{station: std_offset}`. A lookup hits only when the file fingerprint matches AND every stored offset equals the registry's current value. This replaces the whole-table fold (census:314); a registry addition no longer cold-starts everything.
4. **Per-day scoping of the conversion loop.** For each climate_day: select → spans → drop. The high-water becomes the largest (instance, day), not the whole instance.
5. **Work root off tmpfs, removed per instance** (`shutil.rmtree(work_catalog)` after its spans are computed). Default `~/.cache/breezy/replay-census-work/`.
6. **Optional, only if Stage 0 says the scan still dominates:** a read-only memo consumer for non-hit instances. It uses `_load_memo`/`_memo_entry` (preflight_memo.py:85-99,142-153) and never writes.

## 4. Cache invalidation and versioning
- **Key:** `(instance_id, file_fp, algo_version)`, plus a stored `station_offsets`. `file_fp` = sha256 over sorted `(relpath, size, mtime_ns)` (instance_span_cache.py:98-107).
- **Versions:** bump `INSTANCE_SPANS_SCHEMA_VERSION` 1→2 and write to a **new path** `instance_spans.v2.jsonl`. The v1 reader refuses unknown versions (:243-247), so the census never crashes on an old file.
  - Absent v2 = cold start: a full rebuild, the same as `--no-instance-spans-cache` (census:650-653).
  - `SPAN_ALGO_VERSION` stays 1 (the span math is unchanged). Any future change to the math bumps it.
- **Prune on write:** drop entries whose instance_id is no longer listed, and older fingerprints for the same id (census:441 currently only adds).

## 5. /tmp cleanup on kill
- **SIGTERM:** in `main`, install a SIGTERM handler that raises `SystemExit(143)`, so the `TemporaryDirectory` exit and the checkpoint `finally` both run. systemd sends SIGTERM at the timeout; Python's default SIGTERM action skips all cleanup, which is why the 81M dir was left behind.
- **SIGKILL/OOM:** at startup, take an `fcntl` lock on `<work_parent>/.lock` and sweep stale `replay-sufficiency-census-*` dirs. No wrapper change is needed, which keeps the B18 invocation set (replay-daily-run.sh:7-13) intact.
- **One-off at rollout:** remove the existing `/tmp/replay-sufficiency-census-*` dir.

## 6. Tests (RED first; gate = `scripts/ci/run_tests_no_egress.sh`)
Fixtures reuse `_write_binary_option_feather`, `_write_truncated_open_stream` and `_quote_tick` (test_replay_sufficiency_census.py:332-337), plus the `_convert_live_capture`/`_select_capture_instruments` seams (:562-569).

- **E1 equivalence:** 4 synthetic instances (2 CLEAN on multiple days, 1 CORRUPT, 1 LIVE). `run_census` with a cold cache, then a warm cache, then `--no-cache` must give identical tuples (dataclass equality) and identical `write_replay_sufficiency` bytes.
- **E2 negative control:** change one CLEAN instance (append a file, or bump the mtime). The spy must show exactly that instance reconverted and the others not, and the output must equal a full recompute. Also: a stale cached span injected under the old fingerprint must never appear.
- **E3 offsets:** edit one station's offset in a registry stub. Only the instances carrying that station reconvert. Adding an unrelated station reconverts nothing.
- **E4 scan skip:** spy on `scan_instance`/`inspect_feather_file`. Zero calls for warm CLEAN hits; one call per miss, CORRUPT or LIVE instance.
- **E5 checkpoint:** the converter raises on instance k+1. The cache file holds k entries. The rerun converts only the remainder, and the final output equals E1's.
- **E6 cleanup:** a subprocess `main` with a stub converter that sleeps is sent SIGTERM. Exit is non-zero, the work dir is gone, and the cache holds the completed instances. A pre-seeded stale dir is swept on the next start.
- **M1 memory (L-49, LESSONS.md:1558):** run in a fresh child; baseline `ru_maxrss` after imports and warm-up.
  - Assert ΔRSS(warm, N=20 instances) − ΔRSS(warm, N=2) ≤ a fixed small MiB bound, i.e. flat in N.
  - Assert the per-day loop's ΔRSS tracks one day, not the instance's day count.
  - Never tracemalloc: it cannot see Arrow allocations.
- **T1 time as work:** bytes read by the scan on a warm run = 0 for cached instances (counted through the spy). No flaky wall-clock asserts.
- **Unchanged:** every existing census test, the completeness assertion and the unit-limit tests (test_replay_daily_deploy_units.py:27-28).

## 7. File-by-file
| Stage | File | Change |
|---|---|---|
| 0 (read-only) | scratch script | Recompute production fingerprints against the v1 cache and report the hit rate; that tests H2. Time the scan vs conversion per instance, with per-instance ΔRSS, run capped via `systemd-run` with the unit's limits in a quiet window. |
| 1 | `src/breezy/analysis/instance_span_cache.py` | v2 schema, `station_offsets`, a `lookup` that checks offsets, prune, v2 path |
| 1 | `scripts/analysis/replay_sufficiency_census.py` | Fingerprint before scan (:509-521), per-instance checkpoint + rmtree + per-day loop (:371-441), drop the whole-table fold (:284-314), SIGTERM handler + locked sweep + off-tmpfs work root (:657-678) |
| 1 | `tests/unit/test_instance_span_cache.py`, `tests/unit/test_replay_sufficiency_census.py`, new `tests/unit/test_replay_census_memory_bound.py` | E1-E6, M1, T1 |
| 2 (if Stage 0 needs it) | `src/breezy/persistence/preflight_memo.py` | A read-only `load_memoized_report(path, stat)` helper; no writes |
| Rollout | none (ops) | Cold v2 rebuild in one manual capped run, then let the 15:50Z timer run. That gives C12 its unattended run (PROMOTION_PROPOSAL_MECHANISM_2026-09-26.md:46,92). |

MemoryHigh, MemoryMax and TimeoutStartSec are not changed (service:36-37,62).

## 8. Risks
- **R1: the scan skip hides a truncation introduced after caching.** Only an edit that preserves size and mtime could do that (A7, already accepted). Appends change size, which forces a rescan (E2).
- **R2: the per-station offset check misses a case the whole-table fold caught.** Offsets only affect that instance's own windows (census:330-335,411-413). E3 plus E1 cover it.
- **R3: the v2 cold rebuild takes more than 1800s on the first run.** The checkpoint makes progress durable. Run the rebuild manually and capped first.
- **R4: the trigger was H1 and the scan skip is not enough.** Stage 0 decides this before Stage 2.
- **R5: concurrent agents in one tree.** Implement in a worktree with PYTHONPATH set. Never `uv sync` the shared venv.

## 9. SEARCH/CONFIRM firewall compliance
- Rows, reasons, winner selection (`classify_station_day`), the completeness assertion (census:617-620) and the candidate exclusion (:623-627) are untouched.
- Only the provenance of each `InstanceSpan` changes: cached vs recomputed.
- E1/E2 prove byte equality with a full recompute on the same inputs, so the census still counts the same thing (RULING_RA-13…md:26), only incrementally.
- No safety test is weakened, no cap or timeout is raised, and no operator control is assigned.

## 10. Confidence
- **High:** mechanism, file:line facts, and the equivalence design.
- **Medium:** which factor tripped 09-27. H1/H2/H3 are unmeasured; Stage 0 is mandatory before claiming a root cause.
- **Needs a live run to confirm:** the full fix delivering a completed unattended C12 run.

Per the repo delegation order, implementation goes to Codex/grok with the invariants restated in the brief. Claude runs the gate and reviews the diff.
