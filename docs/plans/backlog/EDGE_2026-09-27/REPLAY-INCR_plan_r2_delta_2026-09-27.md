# REPLAY-INCR plan r2: DELTA over r1 (BINDING; it overrides r1 where the two conflict)

Round-1 peers, all reviewing blind:
- architect: REQUEST_CHANGES (3 HIGH, 6 MED, 1 LOW)
- python-reviewer: MEDIUM (C 9 / I 7 / T 6 / R 7 / S 9 / F 8; 2 blocking)
- prediction-market-reviewer: REQUEST_CHANGES (4 items)

All three endorse the direction: harden C6, do not rebuild it, raise no cap.

## I-1. Take the fingerprint BEFORE the scan (architect HIGH)
- Compute exactly one `file_fp` per instance before `scan_instance`, then pass it through. It is the key for the cache lookup and for the cache write.
- It is never recomputed after the scan or after conversion.
- If a file changes between the fingerprint and the scan, the scan either sees the change or the next run misses the cache.
- New RED test E7: a truncated tail is appended between the scan and the cache write. The next run must rescan and classify the instance CORRUPT.

## I-2. Bound the integrity residual on a cache hit (domain item 1; architect MED on the classifier version)
Skipping the scan on a hit removes today's always-on content check. This counter gates a programme-level ruling (RA-13/EDGE-4), so the residual is bounded three ways:
- **Tail probe on every hit, cost O(1):**
  - Each feather or IPC stream file must end with the Arrow IPC end-of-stream marker (continuation `0xFFFFFFFF` + length `0x00000000`), read by seeking to the last 8 bytes.
  - It must also open with a valid first-message prefix.
  - A failed probe is treated as a cache MISS, which triggers a full scan.
  - Test: an in-place tail corruption that preserves size and mtime is caught by the probe (E8).
- **Forced full rescan:**
  - The key gains `rescan_epoch = floor(days_since(2026-09-27) / 7)`.
  - Every cached entry therefore goes stale at least once every 7 days and is rescanned. The cadence is fixed here, not left at "never".
  - Test (E9): an entry cached in epoch k misses in epoch k+1.
- **Classifier version:**
  - The key carries `PREFLIGHT_CLASSIFIER_VERSION`, a new constant in feather_preflight.py.
  - A future change to truncation detection bumps it and invalidates every entry.
- **Residual after these bounds:** a same-size, same-mtime corruption in the middle of a file that leaves the tail intact goes undetected for at most 7 days. This is stated accurately in §8 R1, replacing the r1 wording ("the existing A7 limit"). E10 pins the known divergent behaviour explicitly (domain item 2): the mid-file edit is reported CLEAN until the next epoch, then CORRUPT.

## I-3. Provenance is recorded without changing the counter schema (domain item 4)
- Each run appends one audit line: `census_provenance: run=<stamp> instances=<n> cache_hit=<n> probe_fail=<n> rescanned=<n> epoch=<k>`. It goes to the census stdout, which lands in replay_daily.log.
- Rows in `replay_sufficiency.jsonl` stay schema-identical, so E1's byte-equality holds across cold, warm and no-cache runs.

## I-4. Each run holds a lock on its own work directory (architect HIGH; python blocking 1)
- A run holds an `fcntl.flock` on `<workdir>/.lock` for its whole lifetime.
- The startup sweep removes a `replay-sufficiency-census-*` directory, under the new `~/.cache/breezy/replay-census-work/` root and the legacy `/tmp` prefix, ONLY if it can take that directory's lock non-blocking.
- A live sibling's directory is therefore never removed.
- Test: two concurrent runs, the second one sweeping; the first run's directory survives.

## I-5. The census takes the studies lock (architect MED, L-50)
- The census acquires `breezy-studies.lock` itself: a non-blocking flock with the same semantics as the wrapper.
- A manual sibling run and the timer can therefore never both rewrite the cache.
- The wrapper's existing flock stays in place, and the lock is re-entrant for the same process chain. Design check: if the wrapper already holds the lock, the census inherits the fd or skips; the implementer must verify which.

## I-6. Checkpoint idiom (python non-blocking; adopted)
- Checkpoints are **append-only JSONL**: one record per instance, appended as that instance finishes, with flush + fsync.
- Prune and compact happen once, at the final write, as an atomic rewrite. Total cost is O(n).
- The reader tolerates a torn final line from a SIGKILL by skipping it and counting it.

## I-7. Guard the prune (architect MED)
- Prune runs only after a SUCCESSFUL, non-empty `list_instance_ids`.
- A listing that fails or comes back empty, which is currently turned into `()` at census:503-504, never prunes.

## I-8. SIGTERM (architect MED; python blocking 2 for E6)
- The handler sets a flag. The flag is checked at instance boundaries.
- `SystemExit(143)` is raised only when the process is idle between calls. A long pyarrow or Rust call delays the stop until the call returns.
- Stated worst-case stop latency: one instance's conversion. The lifetime-lock sweep (I-4) is the real backstop for SIGKILL.
- E6 synchronization:
  - The stub converter writes a readiness marker file, then blocks on a pipe.
  - The test waits for the marker, with a bounded poll of at most 10 s, sends SIGTERM, then waits for exit with a timeout of at most 20 s.
  - It never uses a bare sleep.

## I-9. Stage 0 split (architect MED)
- **0a, cheap, runs now:** the L-49 journal/cgroup triage of the 09-27 failure, plus a stat-only recompute of the v1 cache hit rate, which is the H2 test. Both are read-only.
- **0b, heavy:** timing the scan versus the conversion. It runs only after AUD-07 finishes, outside node hours (16:50–01:00Z), away from the 15:50Z timer, under `breezy-studies.lock`, via `systemd-run -p LimitNOFILE=524288` with the unit's memory limits and the pinned interpreter.
- Build I-1, I-2, I-4, I-5, I-6, I-7 and I-8 now; they do not depend on Stage 0. Per-day scoping, r1 §3.4, is **DEFERRED** (YAGNI) until 0b shows the object high-water matters.
- r1's L-49 wording is corrected: the observed CPU/wall of 0.4 is above L-49's threshold of 0.3. 0a checks memory.events and the major faults; the match is not asserted.

## I-10. Rollout: migrate v1, do not cold-rebuild (architect HIGH)
- **Migration.** For each v1 entry, recompute `fold(file_fp_now, table_now)`. If it equals the stored v1 fingerprint, write a v2 entry with `file_fp_now` and the `station_offsets` taken from the stations in its spans. Only real misses start cold.
- **Ordering:**
  1. Merge.
  2. Run a manual census under the studies lock, capped the same way, in the post-AUD-07 quiet window.
  3. Repeat until warm; the checkpoint keeps progress between runs.
  4. Only then let the 15:50Z timer run.
- **Target:** warm census wall time of at most 600 s, leaving headroom inside the shared 1800 s budget for the runner and the proposal step.
- Remove the orphan `/tmp/replay-sufficiency-census-*` directory once, as part of the rollout.

## Unchanged from r1
- Option (a) is chosen; (b) and (c) are rejected.
- No cap or timeout changes.
- The completeness assertion and the winner rule are untouched.
- SEARCH/CONFIRM firewall compliance, as in r1 §9.
- E1–E5, M1 and T1 stay.
