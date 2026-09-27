# EDGE-6 — Operational reliability of the data spine (plan r1, 2026-09-27)

Severity: MED overall. Slice 6b is upgraded to HIGH-trend (see §2.2: the ingest fixed cost grows through the day
and two consecutive runs at 02:15Z and 02:30Z on 09-27 already exhausted the budget).
Author role: code-architect (planning only; read-only investigation, 2026-09-27 ~02:00–02:45Z).
Scope: six independent slices (6a–6f). Each slice has its own acceptance criteria, tests and deploy proof.
Some are observation-only.

Premises the brief stated that the artifacts CONTRADICT (L-10, L-32). These are carried into the slices:

| Brief premise | What the artifacts show | Consequence |
|---|---|---|
| "22 ingest timeouts 09-24..26" | The journal shows **40** `Failed with result 'timeout'`, plus 2 `oom-kill` and 2 `signal`. All of them came from 09-24 10:15Z to 09-26 11:15Z, at `TimeoutStartSec=1800`, and all are the L-49 memory-thrash signature (e.g. 09-26 10:15Z: 5 min CPU over 30 min wall). None of them was the 600 s deadline. | Two populations were conflated. The timeouts are closed by ING-2 S2/S3a plus the drop-in. The **live** problem is different: the post-S2 deadline runs spend 361–478 s (p50 399 s, n=68) of the 600 s budget doing no work, and 3 runs exceeded it. |
| "Recorder instrument set is fixed at its 09:00Z boot until the next rotation" | **False.** The recorder already runs an in-session reload loop (`data.py:1223 _update_instruments`) and dynamically opens shards. On 09-26 it subscribed all 30 09-27 markets at **15:00:15Z**. The venue listed them at **09:46:16–49Z** (`startDate`, from `data/evidence/discovery_set_equality/2026-09-26_pages.json`). | Nautilus plus the existing adapter extension already provide in-session refresh (null hypothesis holds). The defect is the **6 h reload ceiling** (`data.py:303`). It costs about 5 h 13 min of every next-day market's opening tape, every day. |
| "breezy-k1-daily 11.4G" | The journal "memory peak" is 11.8–12G every day since 09-12. It is pinned at `MemoryHigh=12G`, with 0.05–2.1 G of swap. The number that is actually growing is **wall time**: 6 m 51 s on 09-12, 27 m 10 s on 09-27, about +1.35 min/day, against `TimeoutStartSec=1800`. | At that slope the unit will time out in about 2–4 days (09-29..09-30). |

---

## 1. Goal & acceptance criteria (numbered, testable)

Goal state: the data spine (discovery pull, recorder, ingest, nightly studies, capital-flow pull) runs unattended.
- Every scheduled run lands inside its budget.
- Every next-day market is captured from within 15 min of its listing.
- Every persistent failure mode reaches the alert webhook. None is found by hand.

### 6a — discovery-pull timer
- **AC-6a-1** The 09-27 16:52Z run is **timer-triggered**:
  - `systemctl --user show breezy-discovery-pull.timer -p LastTriggerUSec` reads `Sun 2026-09-27 16:52:xx UTC`.
  - `breezy-discovery-pull.service` `ExecMainStartTimestamp` is within 60 s of it (AccuracySec=1min).
- **AC-6a-2** The journal for that invocation contains no `Traceback` and no `ModuleNotFoundError`. It shows `Finished breezy-discovery-pull.service`, `Result=success`, `ExecMainStatus=0`.
- **AC-6a-3** Exactly one of these exists with mtime ≥ 16:52Z:
  - `data/evidence/discovery_set_equality/2026-09-27.json`, or
  - that day's `no_pull.json`, carrying a reason.
  Either one proves the `-m` import path. The content of the pull is AUD-02's concern, not EDGE-6's.
- **AC-6a-4** No `breezy-study-failed@breezy-discovery-pull.service.service` invocation appears after 16:52Z.
- **AC-6a-5** A regression test runs the unit's ExecStart **as the unit would**: the unit's own `WorkingDirectory`, a scrubbed environment, and the repo root not on `PYTHONPATH`. It fails against the pre-2e109ec ExecStart and passes against the current one. The test is parametrized over every unit whose ExecStart runs the venv interpreter directly.
- **AC-6a-6** The "Consumed … memory peak, … memory swap peak" line of the 16:52Z run is recorded. If swap peak > 0, slice 6a-2 (MemoryHigh 128M → 224M, MemoryMax stays 256M) is applied **after** the proof run.

### 6b — quote-ingest time budget
- **AC-6b-1** A no-op ingest run (nothing new to convert) has `elapsed ≤ 60 s` at p90 over 24 h. Today p90 is 455 s.
- **AC-6b-2** The first ingest run after the 09:00Z rotation that sees the rotated instance as dead converts it. Over at most 2 consecutive runs, `deferred_units=0 deferred_instances=0`.
- **AC-6b-3** For every instance, the preflight report produced with the memo is **field-for-field identical** to the one produced cold by `scan_instance`. Proven by test, and by a one-shot host comparison over all 63 instances.
- **AC-6b-4** The deadline line gains `rss_peak_mb=<ru_maxrss>` (value-free, integer). ING-2's drop-in decision can then use a metric that page cache does not dominate (see §2.2 and the ING-2 hand-off).
- **AC-6b-5** Zero change to conversion semantics. The existing ingest suites stay green unmodified: `test_quote_tape_ingest_{cli,deadline,definitions_first,failure_surfacing,bounded_read,bounded_rss}.py`, `test_feather_preflight.py`, `test_quote_tape_salvage_unsupported_type.py`.

### 6c — breezy-k1-daily memory / wall time
- **AC-6c-0** Containment is deployed before 09-28 01:35Z: `TimeoutStartSec=3600`. The 09-28 run finishes with `Result=success`.
- **AC-6c-1** Stage-0 records a passive, read-only memory split (`anon` vs `file` from `memory.stat`, plus `VmHWM`, every 30 s) for the scheduled 09-28 01:35Z run.
- **AC-6c-2** After 6c-2, the K1 report is **byte-identical** (modulo `generated_at`) to the pre-change report on the same tape. The per-run anon peak (`ru_maxrss`) is O(max rows per instrument) and no longer O(total tape rows), shown by a white-box counter test.
- **AC-6c-3** The wall-time slope is re-measured over 3 nights after 6c-2 and projected against `TimeoutStartSec`. If the projection crosses 3600 s within 30 days, 6c-3 (incremental per-instrument fold cache) is queued; otherwise it is recorded PARKED, with the numbers.

### 6d — next-day market capture
- **AC-6d-1** On the first recorder boot after merge (the 09:00Z rotation), the recorder logs its discovery reload ceiling as 900 s, and the node's ceiling is unchanged (6 h).
- **AC-6d-2** On that day, every next-day slug listed at ~09:46Z is logged `subscribing … (new)` no later than listing + 15 min + 60 s.
- **AC-6d-3** L-45 coverage count. By listing + 20 min, `comm -23 <subscribed next-day slugs> <ls order_book_depths/ next-day dirs>` is empty in the live instance. There are zero subscription-rejection ERROR lines. The peak shard count is ≤ 12, which is the count already sustained daily 15:00Z→09:00Z.
- **AC-6d-4** A ceiling clamp with a valid future boundary logs at INFO on the recorder, so a WARN is not emitted every 15 min. The floor clamp and a `None` boundary still log WARN.

### 6e — capital-flow timer
- **AC-6e-1** Already verified now (read-only):
  - `NextElapseUSecRealtime=Sun 2026-09-27 17:30:00 UTC`.
  - `systemd-analyze calendar '*-*-* 17:30:00 UTC'` → next elapse is 09-27 17:30:00 UTC.
  - `LastTriggerUSec` is empty, which proves the 09-26 21:52Z run was a manual start.
- **AC-6e-2** After 17:31Z on 09-27:
  - `LastTriggerUSec=Sun 2026-09-27 17:30:xx UTC`.
  - Service `ExecMainStartTimestamp` is within 60 s of it; `Result=success`; `ExecMainStatus=0`.
  - Exactly one `CAPITAL_FLOW_PULL status=OK` line appears since 17:29Z.
  - A new snapshot appears under `~/.local/share/breezy/derived/capital_flows/` with mtime in [17:30, 17:35]Z.
  - No `breezy-study-failed@breezy-capital-flow-pull.service.service` instance runs.
  - `breezy-portfolio-roi.service` starts **after** the pull's `ExecMainExitTimestamp`.

### 6f — alert for persistently deferred ingest units
- **AC-6f-1** Pending work deferred on **4 consecutive runs and ≥ 60 min** makes the run exit **4** (`EXIT_DEFERRAL_STALLED`). Pending work means the instance is not fully converted, or a per-type or salvage unit was deferred. `OnFailure=` then delivers the existing `study_unit_failed` WARN through `breezy-study-failed@`.
- **AC-6f-2** The stall alerts on the crossing run and every 16th run after it (about 4 h). The runs in between exit 0, so there is no alert storm.
- **AC-6f-3** A single deferral, or a streak below threshold, still exits 0. The S2 contract ("deadline deferral is never a failure") is preserved for that case. `test_run_exits_zero_when_every_non_success_is_a_deferral` stays green unmodified.
- **AC-6f-4** Exit 3 (conversion failed) takes precedence over exit 4 in the same run.
- **AC-6f-5** A deferred instance that was "not evaluated" but is already fully converted (marker-only check) never counts toward a stall. At 02:30Z on 09-27, 24 instances were deferred, most of them no-ops.

---

## 2. Evidence / root cause (file:line)

### 2.1 6a — discovery pull
- 09-26 16:52:47Z: the timer-triggered run failed with `ModuleNotFoundError: No module named 'scripts'` at `scripts/analysis/discovery_venue_pull.py:29` (`from scripts.analysis.discovery_set_equality import …`), under the old direct-file ExecStart. It triggered `OnFailure=`.
- 2e109ec (merge 17:29:43Z) changed `deploy/systemd/breezy-discovery-pull.service:67` to `python -m scripts.analysis.discovery_venue_pull`. The 17:29:46Z run was a **manual** start. It succeeded in 3.2 s and wrote `2026-09-26.json` (`complete: true`). The timer path has not yet run the new ExecStart.
- Loaded state now (verified 02:3xZ): `FragmentPath` is the symlink to the repo file, `NeedDaemonReload=no`, and the loaded `ExecStart` argv carries `-m`. Timer `NextElapseUSecRealtime=Sun 2026-09-27 16:52:00 UTC`, `Persistent=yes`.
- An existing guard, `tests/unit/test_discovery_pull_exec_import.py`, runs the real interpreter with `--help`. Gaps:
  - (i) it hard-codes `cwd=_REPO_ROOT` instead of honouring the unit's `WorkingDirectory=`;
  - (ii) it inherits the test process environment. A future `PYTHONPATH` containing the repo root would mask the defect;
  - (iii) it covers one unit only. `breezy-fee-evidence-pull.service` also runs a script by path. The run-wrappers (`k1-daily-run.sh:68`, etc.) do too, and `k1_cheap_open_settlement.py:103` imports the sibling `tape_arrow_columns` by bare name, which works only because of `sys.path[0]` = the script dir.
- Latent risk: the 17:29Z run peaked at **128.8M, with a 129.9M swap peak**, against `MemoryHigh=128M` (`:31`). The unit is swapping at its throttle ceiling on a 3 s import-only run. The 16:52Z run polls for up to about 20 min.

### 2.2 6b — ingest budget (measured 09-27 02:00–02:40Z)
- Deadline series (`journalctl --user -u breezy-quote-tape-ingest`, first deadline line 09-26 08:07Z): n=68, elapsed min 361 / p50 399 / p90 455 / max 610 s. Runs over 600 s:
  - 11:25Z: 8 units deferred;
  - 19:40Z: 2 instances deferred;
  - 02:25Z on 09-27: 24 instances deferred;
  - 02:40Z on 09-27: 24 instances deferred, 608 s. Two consecutive runs; the trend is rising toward the pre-rotation maximum.
- A run that converts **nothing** takes about 400 s. At 02:06:42Z every instance was `skipped-already-converted` or `skipped (N truncated…)`, with `deferred_units=0`, yet 400 s elapsed. The only logged work was one salvage line at +33 s.
- Mechanism: `run_ingest` (`src/breezy/runtime/quote_tape_ingest_cli.py:1826`) short-circuits only instances that pass `_instance_is_fully_converted`. Every other instance goes to `scan_instance` (`:1850-1853` → `src/breezy/persistence/feather_preflight.py:499`). That function inspects **every** feather file. Each inspection is a message-by-message Arrow decode (`_scan_stream`, `feather_preflight.py:292`), with no memo, repeated every 15 min. Instances that never pass the short-circuit today:
  - `7f353f94` (0.72 GB, 1249 files), `887d2005` (3.3 GB, 719 files) and `c230f4fc` (3.7 GB, 955 files). These are 09-03..09-08 instances whose truncated files are all salvage-marked. They carry only `.converted-binary_option` and **no other type markers**, so they are rescanned forever.
  - The live instance `ea485c90`: 6.6 GB and 630 files at 02:00Z, growing all day. Only the newest file per type group is open (`_open_files_for_instance`, `:1073-1114`). Every closed file is immutable by construction, yet it is re-decoded on every run.
- Measured scan throughput (read-only, `nice 19`, concurrent with a live ingest): `scan_instance(7f353f94)` = 14.0 s for 0.72 GB, about 52 MB/s. About 14 GB per run at 45–52 MB/s ≈ 270–320 s, which is the bulk of the 400 s. Scan time is spent **before** any `admit()`, so it silently eats the conversion budget (`ingest_deadline.py:114-128`).
- The fixed cost is a sawtooth. It is lowest just after the 09:00Z rotation (about 7.7 GB of stuck instances, plus the rotated instance's first full scan and conversion; this explains the post-rotation clustering). It is highest just before the rotation (about 15 GB). Instance order is uuid-lexicographic, so a late-sorting new instance is the one deferred.
- **Memory is page cache, not anon.** During the 02:30Z run the cgroup's `memory.stat` was sampled 26 times: `anon` 148–150 MB throughout, `file` 3.06–7.62 GB, process `VmHWM` 311–315 MB. The journal "memory peak" (12G on most runs since 11:38Z 09-26) is the page cache filling up to `MemoryHigh`. This matters to ING-2 (§11).

### 2.3 6c — K1 daily
- Journal since 09-12: memory peak 11.8–12G every run, swap 0.05–2.1G, wall 6 m 51 s → 27 m 10 s; CPU/wall ≈ 1.0, so CPU-bound, not thrash-bound (L-49 triage). Timeout is `TimeoutStartSec=1800` (`deploy/systemd/breezy-k1-daily.service:53`). Headroom on 09-27 is 2 m 50 s.
- Mechanism (`scripts/analysis/k1_cheap_open_settlement.py`):
  1. **Global dedupe set, O(total tape rows).** `seen: set[tuple[str,int,int]]` in `_stream_depth_ask_observations` (`:600-714`, `seen.add` at `:672`) and in `_stream_quote_ask_observations` (`:729+`). Each holds every deduplicated row since capture began: 19,505,438 depth plus 18,154,451 quote rows (09-27 report §1). At about 150–170 B per tuple entry, the depth set alone is about 3 GB and grows about 1M rows/day. It has a consumer (the preflight `deduplicated_rows` count), so this is not an L-29 leak. It is **unbounded by construction in calendar time**.
  2. **Whole-file `read_all()` on one-row-per-message feathers.** `scripts/analysis/tape_arrow_columns.py:45-46` violates the L-49 amendment: about 5.3 KB per message transient on the largest live file.
  3. **Re-reads the entire tape nightly**, `data/` plus every `live/*` instance (`_tape_files`, `:506-516`). Wall time is O(total tape): this is the growth.
  4. Page cache from reading more than 20 GB is charged to the cgroup, like 6b. The anon/file split for K1 is **not yet measured**; the Stage-0 below measures it.
- Verdict: the size is **partly legitimate** (page cache, a per-file transient) and **partly unbounded-by-construction** (the dedupe set; the full-history re-read). It is not a consumer-less leak like L-29, and it is not an L-31 multiset loop. Left alone, the unit **times out** in about 2–4 days. The memory peak is already pinned by the cap.
- Side finding (validity, not reliability): K1 measures the "cheap **open**" of D+1 rungs. Because of 6d, the recorder's first D+1 observation is about 5 h after the actual listing. The "first genuine ask" K1 folds is therefore not the open. Record this in the K1 report caveats once 6d lands (§11).

### 2.4 6d — next-day capture
- `data.py:1223 _update_instruments` is the in-session reload loop, the adapter's Nautilus-native extension point (Nautilus `connect()` provides no rediscovery; the docstring at `:1225-1233` says so). The next delay comes from `_next_reload_delay_secs` (`:1193`) via `derive_reload_delay_secs` (`:351`). It targets the soonest known `activation_ns`/`expiration_ns`, clamped to `[60 s, 6 h]` (`:287`, `:303`).
- At the 09:00Z boot, the next-day cohort is **not yet listed** (09:46Z), so its activation is not a known boundary. The soonest known boundary is today's 05:00Z-next-day expiry, which is ceiling-clamped to 6 h, giving a reload at 15:00Z. Journal 09-26: `discovery count before=30 after=60` at 15:00:15Z, then 30 × `subscribing tc-temp-*-2026-09-27-* (new)`, shards 6→11 opened, `clamped to the ceiling of 21600s`.
- Subscription cap (memory venue-ws-subscription-cap-is-shared; L-45): the pool logs `subscriptions per slug=2 slugs per shard=5`. Sixty concurrent slugs use 12 shards, and this is **already sustained daily** from 15:00Z to the 09:00Z rotation. Discovering the cohort at about 10:00Z instead of 15:00Z extends that window by about 5 h. It does not raise the peak slot or connection count.

### 2.5 6e — capital-flow timer
- `breezy-capital-flow-pull.{service,timer}` were symlinked and enabled on 09-26 at 21:52:24Z (link mtimes; `stamp-breezy-capital-flow-pull.timer` mtime 21:52:24). That is after that day's 17:30Z slot. `Persistent=true` only catches up a slot missed **since the stamp**, so no catch-up was due. The 21:52:24Z run (7 records, OK) was a manual start: `LastTriggerUSec` is empty.
- Root cause of "never fired on schedule": install timing, not a defect. `NextElapseUSecRealtime=Sun 2026-09-27 17:30:00 UTC` (verified).

### 2.6 6f — deferred units have no alert
- `ingest_deadline.py:40-43` defines `DEFERRED_DEADLINE`. `run()` prints the `deadline` count line (`quote_tape_ingest_cli.py:2193-2200`) and exits 0 on any deferral, by contract (`breezy-quote-tape-ingest.service` exit-contract comment). The only alert path is `OnFailure=breezy-study-failed@%n.service` (`:22`). It fires only on non-zero, timeout or OOM. A deferral streak is therefore silent.
- It is live now: 02:25Z and 02:40Z each deferred 24 instances, including the live instance `ea485c90` (it sorts late). No alert fired, and none could.
- The notifier (`src/breezy/runtime/study_failure_notifier.py`) has no dedupe. An exit-code design must rate-limit itself.

---

## 3. Options & trade-offs

### 6b — the brief's three options plus the root-cause option
| Option | Effect on the 400 s fixed cost | Verdict |
|---|---|---|
| Raise the 600 s budget | None. It lets the sawtooth grow into `TimeoutStartSec` and lengthens the window in which a mid-run kill leaves a poison breadcrumb. | Rejected: treats the symptom. The ceiling is containment, not a fix (L-29). |
| More chunking | None. ING-2 S3b already chunks EXTEND, and conversion is not where the time goes (salvage plus conversion logged ≤ 33 s on no-op runs). | Rejected: duplicates ING-2 and misses the cost. |
| Split the salvage step out | About 1 s/run. The salvage work is already marker-gated (`:1609-1611`, T-n4-noop). | Rejected: salvage is not the cost. |
| **Preflight memo keyed by file identity** (chosen) | About 14 GB/run of re-decode drops to stat calls plus decoding of the few newly-closed or open files. | **Chosen.** Report-identical, so zero semantic change. Small (one module plus one call site). |
| Terminal-mark the 3 stuck instances | Removes about 7.7 GB/run. Needs Stage-0 on why the type markers never land. | **Deferred (6b-2, LOW):** after the memo they cost only stat calls. Reopen if the memo leaves them above 5 s/run. |

### 6c
| Option | Pros | Cons |
|---|---|---|
| C0 raise `TimeoutStartSec` 1800→3600 | One line; buys about 3 weeks at the current slope | Containment only; holds `breezy-studies.lock` longer (01:35–≤02:35Z, still outside the protected window) |
| C1 retire the K1 timer | Frees about 27 min and 12G nightly; K1 is DEAD on the Kalshi prior ≥2c | K1 on PM tape is still an UNDERPOWERED live measurement. Retiring it is a research-programme ruling, not an ops call. It goes to the peer loop only if C2+C3 cost more than they return. |
| **C2 bounded memory** (chosen): coalesced read plus per-instrument dedupe scope | Removes the O(total rows) set and the `read_all` transient; equivalence-testable | Does not fix O(tape) wall time |
| C3 incremental fold cache per instrument, keyed by the file-fingerprint set | Wall time becomes O(changed instruments), about the last 3 climate days | New derived artefact and invalidation logic; build only if the post-C2 slope demands it (AC-6c-3) |

### 6d (null hypothesis first)
| Option | Mechanism | Verdict |
|---|---|---|
| N0 Nautilus-native `InstrumentProviderConfig`/periodic reload | Nautilus `LiveDataClient.connect()` offers no rediscovery. The adapter's `_update_instruments` task **is** the native-extension implementation of periodic reload (the same pattern as bundled adapters' `update_instruments_interval_mins`), and it is **already running**. | Holds. Nothing new to build; tune the existing extension. |
| D1 lower the shared `DISCOVERY_RELOAD_CEILING_SECS` 6 h → 15 min | One constant | Also changes the **live node's** reload cadence (blast radius on the trading process) |
| **D1′ per-role reload ceiling** (chosen): a `discovery_reload_ceiling_secs` config field, default 21600 (node unchanged); the recorder config sets 900 | Recorder-only; still "derived boundary, clamped by a Breezy policy guard" (G-19 B2: quotas and guards are Breezy policy, not venue facts; `config.py:15-36`) | 96 vs 4 discovery GETs/day on the recorder. That is ≤ 4/h against a 6/min quota. |
| D2 derived "next-listing" boundary (latest `activation_ns` + 24 h, then floor-poll in a bounded window) | Hits the open within 60 s | More logic. Edge cases: the venue skips about 9% of station-days (memory venue-skips-station-days); listing drift. Queue only if a study needs the first 15 min of the open. |
| D3 move the rotation to about 10:00Z | Boot after listing | A schedule hack that silently breaks on listing drift. It also moves a 09:00Z anchor that the digest (09:20Z), ING-2 and the rotate-timer rationale depend on. Rejected. |

### 6f
| Option | Verdict |
|---|---|
| **F1 in-process streak state plus exit 4 on crossing/re-alert** (chosen) | Reuses the delivered `OnFailure` → `breezy-study-failed@` → `alerts.env` path. Ingest stays socket-free (NO-SEND posture unchanged). |
| F2 separate watcher unit reading the journal | A second unit, a journal-parsing contract, and a new failure surface |
| F3 catalog-freshness alert (outcome-based) | Cause-agnostic and attractive, but it is a different item (freshness SLO). Named as a follow-up. |

---

## 4. Architecture & data flow

- **6b.** `run_ingest` → for each instance not fully converted: `scan_instance_memoized(catalog_root, instance_id, subdirectory)` (new, `breezy/persistence/preflight_memo.py`).
  - Load `<instance_dir>/.preflight-memo-v1.json`, which maps a file name to `{st_ino, st_size, st_mtime_ns, report fields}`.
  - For each feather file in `iter_feather_files` order, reuse the cached report if `(ino, size, mtime_ns)` matches. Otherwise call `inspect_feather_file`.
  - Build the `PreflightReport` in the same order. Atomically rewrite the memo (`tmp` + `os.replace`) only if it changed.
  - Corrupt, unknown-version or unreadable memo: ignore it, scan cold, log one WARN, rewrite.
  - Single writer: the ingest unit. Hand-runs are already banned while it is active (unit comment `:83-86`, L-50).
  - `scan_instance` itself is untouched, so its other callers (preflight CLI, salvage) see no change.
- **6b-4.** `run()` appends `rss_peak_mb` (`resource.getrusage(RUSAGE_SELF).ru_maxrss // 1024`) to the deadline line.
- **6c-2.** `_stream_*_ask_observations`:
  1. Index files by instrument: the schema metadata `instrument_id` via `pa.ipc.open_stream(...).schema` for feather, the parquet schema metadata for parquet (schema only, no body).
  2. For each instrument in sorted order, stream its files through `read_feather_coalesced` (the S3a helper) for feather or `pq.ParquetFile.iter_batches` for parquet.
  3. Dedupe with a set scoped to **that instrument**, then fold into the same callback. Discard the set.
  4. Aggregate the preflight counters exactly as today.
  `build_population` and `_assemble_population` are unchanged.
- **6c-3** (conditional). A per-instrument fold result `{entry, first_obs_by_day, rows, failures}` is cached under `~/.local/share/breezy/k1/fold-cache-v1/`, keyed by the sorted file-fingerprint tuple. An instrument whose fingerprint set is unchanged skips decode.
- **6d.**
  - `PolymarketUSDataClientConfig.discovery_reload_ceiling_secs: float = 21600.0`, validated as > floor.
  - `derive_reload_delay_secs(…, ceiling_secs=…)`; the module constant stays as the default.
  - The recorder's `build_quote_tape_node_config` (or `quote_tape_cli.run` before the build) sets 900. The node factory path is untouched.
  - The boot INFO in `quote_tape_cli.py:263-269` also prints the ceiling.
  - `_next_reload_delay_secs` logs a ceiling clamp with a non-`None` future boundary at INFO. Floor clamps and a `None` boundary keep WARN.
- **6f.**
  - `run()` → after the results merge, compute `pending_deferred` = per-type/salvage deferred units, plus "not evaluated" instances that fail `_instance_is_fully_converted`.
  - Read and update `<catalog_root>/.ingest-deferral-streak-v1.json`: `{consecutive_runs, first_deferred_utc, runs_since_alert}`. Reset to empty when `pending_deferred == 0`.
  - If `consecutive_runs ≥ 4` and age ≥ 60 min, and this is the crossing run or `runs_since_alert ≥ 16`, print `breezy-quote-tape-ingest: DEFERRAL_STALLED runs=… age_s=… pending_units=…` (counts only) and return 4.
  - Exit precedence: 2 (usage) > 3 (conversion failed) > 4 > 0.

---

## 5. File-by-file plan

| File | Slice | Change |
|---|---|---|
| `tests/unit/test_unit_execstart_imports.py` (new) | 6a | Parametrized over every `deploy/systemd/*.service` whose ExecStart argv[0] is the venv python. Honour `WorkingDirectory=` (host prefix → worktree), use a scrubbed env (`PATH`, `HOME`, `PYTHONPATH=<wt>/src` only; assert the repo root is absent), substitute `--help`, and assert rc 0 with no `ImportError`. Supersedes `test_discovery_pull_exec_import.py`. **Keep that file** (it is a guard; never delete it). |
| `tests/unit/test_run_wrapper_python_imports.py` (new, optional in the same slice) | 6a | Regex-extract `"$REPO/.venv/bin/python" "$REPO/scripts/…py"` from `deploy/systemd/*-run.sh`; run the same `--help` import check |
| `deploy/systemd/breezy-discovery-pull.service` | 6a-2 (conditional on AC-6a-6) | `MemoryHigh=224M` (MemoryMax 256M unchanged; `test_memory_max_is_at_most_256m` holds) |
| `src/breezy/persistence/preflight_memo.py` (new) | 6b | `scan_instance_memoized`, `MEMO_FILENAME`, `MEMO_VERSION`; about 120 lines |
| `src/breezy/runtime/quote_tape_ingest_cli.py` | 6b, 6f | 6b: `:1853` call site → memoized; `rss_peak_mb` on the deadline line (`:2196-2200`). 6f: `EXIT_DEFERRAL_STALLED = 4`; streak update in `run()`; module-docstring exit table |
| `src/breezy/runtime/ingest_deferral_streak.py` (new) | 6f | Pure streak state machine plus atomic JSON I/O; no breezy imports beyond stdlib (mirrors `ingest_deadline.py`'s isolation) |
| `deploy/systemd/breezy-quote-tape-ingest.service` | 6f | Comment-only update of the exit contract (`0/2/3` → `0/2/3/4`); no directive change |
| `deploy/systemd/README.md` | 6b, 6f, 6e | Exit 4; memo file; the rule "a timer enabled after its slot first fires next day" |
| `deploy/systemd/breezy-k1-daily.service` | 6c-0 | `TimeoutStartSec=3600`, with a containment comment citing this plan and L-29 |
| `scripts/analysis/tape_arrow_columns.py` | 6c-2 | Feather branch → `breezy.persistence.feather_read.read_feather_coalesced` |
| `scripts/analysis/k1_cheap_open_settlement.py` | 6c-2 | Instrument-grouped streaming, per-instrument `seen`; `_load_stream` for `binary_option` unchanged (14k rows) |
| `src/breezy/adapters/polymarket_us/config.py` | 6d | `discovery_reload_ceiling_secs` field plus `__post_init__` validation |
| `src/breezy/adapters/polymarket_us/data.py` | 6d | `derive_reload_delay_secs(ceiling_secs=…)`; the log-level rule in `_next_reload_delay_secs` |
| `src/breezy/runtime/quote_tape_cli.py` / `node_config.py` | 6d | Recorder sets 900; the boot INFO line prints the ceiling |
| `docs/plans/backlog/ING-2_2026-09-25/README.md` | hand-off | One-line pointer: the drop-in decision should use `rss_peak_mb` / `anon`, not the journal "memory peak" (§2.2) |

No Nautilus file is touched. No `.venv` edit. No new egress. No operator control or enablement is touched.

---

## 6. Test strategy (RED first; failure and edge paths)

### 6a
- `test_every_venv_python_execstart_imports_under_its_working_directory[breezy-discovery-pull.service]`: RED against the pre-2e109ec ExecStart (checked out via `git show be06f14^:deploy/systemd/breezy-discovery-pull.service` into a tmp fixture), GREEN now.
- `test_…[breezy-fee-evidence-pull.service]`: characterization (L-33). It is expected GREEN; mutation evidence is to break its import and see RED.
- `test_execstart_env_excludes_repo_root_from_pythonpath` (guards the masking path).
- `test_execstart_working_directory_is_honoured` (a unit with `WorkingDirectory=/tmp`-mapped fixture → the `-m` form must fail, proving the test reads the directive).
- Edge: `%h` and `${VAR}` expansion in argv. Tokens after the module are dropped and replaced by `--help`.

### 6b
- `test_memo_report_equals_cold_scan_field_for_field` (intact, truncated, empty-file, empty-stream and unreadable fixtures written through the real `StreamingFeatherWriter` path where feasible; L-42).
- `test_memo_hit_performs_zero_stream_decodes` (count `_scan_stream` calls; RED today: N decodes on the second call).
- `test_memo_invalidates_on_size_change`, `…_on_mtime_change`, `…_on_inode_change` (replace-by-rename).
- `test_memo_new_file_scanned_removed_file_dropped`.
- `test_corrupt_memo_falls_back_to_cold_scan_and_warns_once`; `test_unknown_memo_version_ignored`.
- `test_memo_write_is_atomic_and_skipped_when_unchanged`.
- `test_run_ingest_uses_memoized_scan_and_outcomes_unchanged` (golden outcome tuple across 2 runs).
- `test_deadline_line_carries_rss_peak_mb_integer`.
- Host one-shot (deploy proof, not the gate): a read-only script compares memo vs cold reports for all 63 instances. Run it in a quiet window under `systemd-run --user -p MemoryMax=2G`.

### 6c
- `test_population_identical_before_and_after_instrument_grouping` (extends the existing equivalence to `_build_population_materialized`).
- `test_dedupe_set_peak_is_bounded_by_max_rows_per_instrument` (white-box `peak_seen` counter; RED today: peak = total rows).
- `test_feather_read_uses_coalesced_reader` (monkeypatch spy; RED today).
- `test_duplicate_rows_across_data_and_live_still_deduplicated` (same `(id, ts_event, ts_init)` in a parquet and a feather).
- `test_preflight_counts_unchanged` (raw/dedup/instruments/failures).
- `test_truncated_live_feather_still_counted_as_failure_not_zero_rows` (L-8).

### 6d
- `test_config_default_ceiling_is_six_hours` (the node keeps today's behaviour).
- `test_config_rejects_ceiling_at_or_below_floor`.
- `test_derive_reload_delay_honours_role_ceiling` (RED: no parameter today).
- `test_recorder_config_sets_900s_ceiling_and_node_config_does_not` (builds both configs from a test env).
- `test_ceiling_clamp_with_future_boundary_logs_info_on_recorder`; `test_floor_clamp_still_warns`; `test_none_boundary_still_warns`.
- Existing `tests/unit/test_polymarket_us_autonomy_g19.py:332-363` stays green: the constant is unchanged as the default.

### 6f
- `test_streak_below_threshold_exits_zero`.
- `test_fourth_consecutive_pending_deferral_after_60min_exits_4`.
- `test_three_runs_or_under_60min_do_not_alert`.
- `test_realert_every_16_runs_while_stalled`; `test_runs_between_realerts_exit_zero`.
- `test_streak_resets_on_a_run_with_no_pending_deferral`.
- `test_not_evaluated_but_fully_converted_instance_never_counts`.
- `test_conversion_failure_exit_3_wins_over_stall`.
- `test_stall_line_is_value_free` (counts only, no paths).
- `test_corrupt_streak_file_resets_and_warns`.
- `test_dry_run_never_touches_streak_file`.
- `test_onfailure_notifier_declared_on_ingest_unit` (existing coverage; re-asserted).
- Existing `test_run_exits_zero_when_every_non_success_is_a_deferral` stays green **unmodified** (below threshold).

The gate for every slice: `scripts/ci/run_tests_no_egress.sh`, with `PYTHONPATH=<wt>/src`, `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python` and basetemp under `/home/jon/.cache/breezy-gate/`. Then `lint-imports`. Unit-launched gates add `-p LimitNOFILE=524288`.

---

## 7. Execution order & parallelism

| When (UTC) | Action | Parallel? |
|---|---|---|
| Now → 09-27 16:52 | 6a tests (worktree A); **no unit change before the proof run** | yes, with B/C/D |
| Now → 09-28 01:30 | 6c-0 containment (a one-line unit change plus daemon-reload), then 6c-2 (worktree C) | yes |
| Now → 09-28 08:45 | 6d (worktree D); merge before 08:45Z so the 09:00Z rotation boots it | yes |
| Now → any gap | 6b (worktree B), then 6f on top of 6b. **Serial**: same file, `quote_tape_ingest_cli.py`. Full gate after each merge (L-43). | 6b ∥ A/C/D; 6f after 6b |
| 09-27 16:52 / 17:30 | Observe 6a / 6e proofs (observation only) | — |
| 09-28 01:35 | 6c Stage-0 passive sampler (read-only `systemd-run --user` unit polling the K1 cgroup `memory.stat` every 30 s until the K1 `ActiveState ∉ {active, activating}`) | — |

Implementation routing: `tdd-guide` seeded with python-testing/python-patterns; independent review by `python-reviewer`. `cloudflare`/`laravel` are not applicable. Codex is review-only. Worktrees use their own scratchpad (memory give-each-agent-its-own-scratchpad).

---

## 8. Deploy & verification (what proves it live)

- **6a.** Nothing to deploy for the proof. At ≥ 16:53Z:
  - `systemctl --user show breezy-discovery-pull.timer -p LastTriggerUSec` and `systemctl --user show breezy-discovery-pull.service -p ExecMainStartTimestamp,Result,ExecMainStatus`;
  - `journalctl --user -u breezy-discovery-pull --since '2026-09-27 16:50' --no-pager` shows no Traceback, shows Finished, and gives the Consumed line (memory/swap peak);
  - `ls -la --time-style=full-iso data/evidence/discovery_set_equality/`;
  - `systemctl --user list-units --all 'breezy-study-failed@*'` shows no new instance.
  If the node never spawned (no initial summary by 17:12Z), `no_pull.json` still proves the import. The tests go live on merge (gate only).
- **6b.** Merge in a gap: `systemctl --user show breezy-quote-tape-ingest -p ActiveState` must be `inactive` and the next `*:0/15` tick at least 3 min away. Then:
  - The first run writes `.preflight-memo-v1.json` in the non-converted instances (cold; about 400 s as today).
  - Proof: the second run's deadline line has `elapsed ≤ 60` and `rss_peak_mb` present. The host one-shot memo-vs-cold comparison reports 63/63 identical.
  - 09-28 09:15–09:45Z: the rotated instance converts with deferral 0 within ≤ 2 runs (journal `ingested …` rows, not all `skipped-already-converted`). This is the same observation ING-2 owes, so it is recorded once and cross-referenced.
- **6c.**
  - 6c-0: `systemctl --user daemon-reload`, then `systemctl --user show breezy-k1-daily -p TimeoutStartUSec` = `1h`.
  - 09-28 01:35Z: run `Result=success`, and a new `k1_daily.log` line.
  - 6c-2 is live on the next 01:35Z. Proof: the K1 report equals the previous night's modulo the new tape (plus the equivalence test). The Stage-0 sampler shows the anon peak ≤ 1.5 GB (target; re-baselined after Stage-0) and `rss_peak` reported.
- **6d.** Live at the next 09:00Z rotation (`try-restart`). **Never** restart the recorder ad hoc: irreplaceable tape. Proof on 09-28:
  - the recorder journal's boot INFO shows `ceiling 900s`;
  - `subscribing tc-temp-*-2026-09-29-* (new)` at ≤ listing + 16 min;
  - `pool: … shards=12` max;
  - zero subscription-reject ERRORs;
  - the L-45 `comm -23` check is empty by listing + 20 min;
  - the node's next spawn log still shows the 6 h cadence (INFO/WARN line with `21600`).
- **6e.** Commands per AC-6e-2, run at ≥ 17:31Z on 09-27; add `systemctl --user show breezy-portfolio-roi.service -p ExecMainStartTimestamp` at ≥ 17:41Z. There is no code change. Record in PROGRESS as "fired on schedule 09-27 17:30Z".
- **6f.** Live on the next ingest tick after merge.
  - Positive control, without waiting for a real stall: in a scratch catalog root (never the production root), `--deadline-seconds 1` over 4 runs with a pinned clock produces exit 4 and the stall line.
  - Delivery proof: `systemd-run --user --wait -p OnFailure=… /bin/false` is **not** used. Delivery through `breezy-study-failed@` is already proven by AUD-15a.
  - Production proof: `journalctl --user -u breezy-quote-tape-ingest | grep DEFERRAL_STALLED` stays empty while 6b holds the budget. If a real stall occurs, the webhook alert is observed.

---

## 9. Risk register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | Memo returns a stale report for a file rewritten in place with identical size and mtime | VL | H | Key on inode plus size plus `mtime_ns`. The writer is append-only and the recorder never rewrites a closed file (`_open_files_for_instance` docstring). Version the memo. |
| R2 | Memo write into the **live** instance dir races the recorder | L | M | A distinct dot-file name that `iter_feather_files` ignores; atomic replace; the recorder never lists dot-files |
| R3 | Merge mid-ingest-run mixes module versions | L | M | Merge only in an inactive gap (§8) |
| R4 | 6d raises the node's discovery rate | — | — | Designed out: per-role field; the node default is unchanged; test pins it |
| R5 | A venue connections-per-key limit is exceeded by extended 12-shard hours | L | H | The peak count is unchanged and already sustained 18 h/day. L-45 coverage count on the first day. Rollback = revert the config line (live at the next rotation). |
| R6 | 6f alert storm or notifier loop | L | M | Edge-triggered plus 16-run re-arm; the notifier has no `OnFailure` (AUD-15a) |
| R7 | K1 containment hides a real runaway | M | M | Named containment (L-29). 6c-2/6c-3 carry the cause. Stage-0 measures. |
| R8 | 6c-2 changes K1 numbers | L | H | Byte-equivalence test against the materialized reference plus a host A/B on the same tape |
| R9 | 6a-2 MemoryHigh bump confounds the proof run | — | — | Applied only after 16:52Z (sequenced) |
| R10 | The 3 stuck instances hide a real conversion gap (rows never landed) | M | M | 6b-2 Stage-0 is queued with evidence; out of the critical path |
| R11 | A test fixture writes into the production catalog | L | H | All fixtures under `tmp_path`/basetemp; scratch catalog for the 6f positive control (L-27 analogue) |

---

## 10. LESSONS / invariant compliance

- **Nautilus immutable (CLAUDE.md, L-1, L-11).** 6d proves the null hypothesis: the refresh exists as the adapter's native-extension reload task, so only its policy is tuned. 6b and 6c use Breezy-owned readers plus the S3a helper. No Nautilus edit.
- **L-10 / L-32 / verify-premises.** Three brief premises were corrected with artifacts (header table).
- **L-29.** The K1 and ingest caps are containment; causes are addressed (6b memo, 6c-2). **L-49** triage was applied (CPU/wall, `memory.stat` anon vs file) and the amendment is enforced (no `read_all` on one-row streams, 6c-2). **L-31**: K1 dedupe scope is per instrument, with a counted test.
- **L-45.** Slot math is unchanged; first-day verification by coverage count.
- **L-50.** Memo and streak files have a single writer, atomic replace, and the hand-run ban.
- **L-42.** Fixtures go through real writer paths where feasible. **L-33**: characterization tests carry mutation evidence. **L-43**: full gate after every merge. **L-51**: no installer or stash in worktrees; exact interpreter.
- `allow_short` is untouched. No safety, settlement, contract or NO-SEND test is weakened: the existing ingest exit-0 test is kept, and the exit contract is widened by one reviewed code (4). No operator cap is read or assigned. Enablement and the A1 halt are untouched. Durable processes go via `systemd-run --user`. Oneshot waits use `ActiveState ∉ {active, activating}`. Never kill the node. The recorder deploys only via the 09:00Z rotation.

---

## 11. Dependencies

- **ING-2 (not duplicated).** ING-2 still owes (a) the post-rotation EXTEND observation and (b) removal of `zz-memory-containment-TEMPORARY.conf`. EDGE-6 does neither. It hands ING-2 two things:
  - Finding: the journal "memory peak" is page-cache-dominated (anon about 150 MB versus a peak of 3–7.6 GB file). ING-2's "peak ≪ 12G" criterion should read `rss_peak_mb` (6b-4) or `memory.stat anon`.
  - Design point: 6b-1 lowers per-run read volume, so cache pressure after any drop-in removal is lower.
  The 6b 09-28 rotation proof and ING-2's owed observation are the same run and are recorded once.
- **AUD-02** owns the discovery-pull content; EDGE-6 owns only the run proof (6a). **FU-13b** owns capital-flow content; 6e is the schedule proof.
- **EDGE items:** no hard dependency on EDGE-1, EDGE-3, EDGE-4 or EDGE-5. Soft: EDGE-5 (re-arm edge estimate on real ladders) and EDGE-4 (calibration parity) consume tape completeness. 6d adds about 5 h/day of D+1 opening tape, and 6b/6f keep the catalog current. Any EDGE item that reads K1 or D+1 "open" statistics must note the pre-6d capture lag (§2.3 side finding).

---

## 12. Confidence self-assessment & unknowns

| Slice | Confidence | Main unknown |
|---|---|---|
| 6a | HIGH | Whether the node spawns at 16:50Z (affects `json` vs `no_pull.json`; either proves the import). Whether the 128M throttle slows a 20-min poll. |
| 6b | HIGH on cause (measured decode throughput × bytes ≈ elapsed); MED-HIGH on the ≤ 60 s target | The exact post-memo cost of newly-closed files per 15 min, and whether the 3 stuck instances' files are fully static (memo handles both; measured in the first 2 runs) |
| 6c | MED | The K1 anon/file split is unmeasured (Stage-0 on 09-28). The timeout date is uncertain ±1 day because nightly wall time varies by ±2 min. |
| 6d | HIGH | The venue connections-per-key limit (unmeasured, but 12 connections are already sustained daily) |
| 6e | HIGH | None beyond host uptime at 17:30Z |
| 6f | HIGH | Threshold tuning (4 runs / 60 min / 16-run re-arm are Breezy policy; revisit after 2 weeks of streak data) |

Open questions for the peer review (not for the operator):
- Q1: Should C1 (K1 retirement) be decided now by research ruling, avoiding 6c-2/6c-3 entirely?
- Q2: Is 900 s the right recorder ceiling, or should D2 (the derived listing boundary) be built now, because K1 measures the *open*?
- Q3: 6b-2: diagnose why 7f353f94/887d2005/c230f4fc never earn type markers (possibly a pre-GL-14 legacy path) — hygiene, or a hidden unconverted-row gap?
