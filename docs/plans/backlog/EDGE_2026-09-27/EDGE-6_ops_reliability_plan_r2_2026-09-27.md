# EDGE-6 — Operational reliability of the data spine (plan r2, 2026-09-27)

Supersedes r1 (`EDGE-6_ops_reliability_plan_r1_2026-09-27.md`). Author role: code-architect (planning only, read-only).
Round-1 verdicts: python-reviewer APPROVE; architect REQUEST_CHANGES. r2 applies every coordinator ruling (C-1..C-8).
Re-verified this session (~03:40–04:10Z 09-27) against artifacts; new evidence is cited inline.

## r1→r2 changes

| # | Ruling | What changed in r2 |
|---|---|---|
| C-1 | 6c-0 is DONE | 6c-0 recorded as **DONE**: `~/.config/systemd/user/breezy-k1-daily.service.d/zz-timeout-TEMPORARY.conf` (`TimeoutStartSec=3600`), daemon-reload ~03:40Z 09-27. Re-verified: `TimeoutStartUSec=1h`, `DropInPaths` = that file only. Removal condition in §6c. The repo unit file is **not** edited (r1's `breezy-k1-daily.service` row dropped). |
| C-2 | 6c = K1 retirement ruling first | 6c is now **6c-R: a C1 retirement ruling sub-plan** sent to the peer loop, with the six cited facts plus two new ones (the wrapper has no deadline stop; the script is a library). 6c-2 (per-instrument dedupe) runs **only if the ruling KEEPS K1**. 6c-3 is **dropped**. |
| C-3 | 6d uses the existing override | 6d = one line, `Environment=POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS=15`, in `breezy-quote-tape.service` only (after `:93`). Dropped: the config field, the `derive_reload_delay_secs` parameter, AC-6d-4 and all their tests. Idle timeout corrected to 600 s. Combined connection count stated. Reconnects/h added to AC-6d-3. D2 (listing-time prediction) **rejected**. |
| C-4 | 6b data-loss fix (blocking) | Any file in `open_files` is never memoized. The key is the **same pre-scan stat** `_inspect` takes (`feather_preflight.py:379-386`), with key = `(st_dev, st_ino, st_size, st_mtime_ns)`. This needs a small additive seam in `feather_preflight.py`. New test `test_live_open_file_never_memoized`. Concurrency stance stated explicitly. |
| C-5 | 6f streak semantics | Exit-3 behaviour for `runs_since_alert` specified. The streak file is `<catalog_root>/.ingest-deferral-streak-v1.json` (catalog root, never `live/`). **New:** the "pending" predicate must not count the three stuck instances (see Q3 answer), or 6f alerts on day 1. |
| C-6 | ING-2 corrected criterion | Hand-off rewritten as an **ING-2 row amendment**. The deciding run is the post-rotation conversion run 09:15–09:45Z. Three-part removal test (anon/rss ≤ 2G, CPU/wall ≥ 0.8, `memory.events high` < 1/s of wall), plus a sampling procedure. |
| C-7 | 6a MemoryHigh bump | Verified: MemoryHigh=128M, MemoryMax=256M, MemorySwapMax=infinity, TimeoutStartSec=30min. 09-26 evidence is recorded (§2.1). Recommendation: **do not bump before 16:52Z**. The evidence shows reclaim but not throttling harm. |
| C-8 | Priorities + Q3 | Priority table added (§0). r1 Q3 **answered** from code plus on-disk markers (§2.2.1): a structural marker-promotion gap. Low data risk, and one known unrecoverable file. |

---

## 0. Priorities (coordinator ruling C-8)

| Priority | Item | Deadline / trigger |
|---|---|---|
| **URGENT** | 6a proof: timer-triggered discovery pull | 09-27 16:52Z (observe at ≥ 16:53Z) |
| **HIGH** | 6d recorder reload override (one unit line) | Merge + `daemon-reload` before **09-28 08:45Z**, so the 09:00Z rotation boots it |
| **HIGH** | 6b preflight memo (with the C-4 fix) | Before the 09-28 09:00Z rotation if possible; merge only in an inactive ingest gap |
| **HIGH (hand-off, not EDGE-6 code)** | ING-2 row amendment (§11.1): corrected drop-in removal criterion | Applies to the 09-27 09:15–09:45Z run |
| MED | 6f deferral-stall alert | Serial, **after** 6b merges (same file) |
| MED | 6c-R K1 retirement ruling → 6c-2 only if KEEP | Ruling before 10-01T12:00Z (driver deadline) |
| MED | 6a regression tests (ExecStart-as-unit) | Any time. Tests only; no unit change before 16:52Z |
| LOW | 6b-2 marker promotion for the 3 stuck instances (Q3) | After 6b. Only if 6f's predicate proves too complex, or post-memo cost > 5 s/run |
| Observation only | 6e capital-flow timer | 09-27 17:30Z (observe at ≥ 17:31Z) |
| DONE | 6c-0 K1 timeout containment drop-in | Deployed ~03:40Z 09-27 |

---

Premises the brief stated that the artifacts CONTRADICT (L-10, L-32), carried from r1 and still valid:

| Brief premise | What the artifacts show | Consequence |
|---|---|---|
| "22 ingest timeouts 09-24..26" | The journal shows **40** `Failed with result 'timeout'`, plus 2 `oom-kill` and 2 `signal`. All come from 09-24 10:15Z to 09-26 11:15Z, at `TimeoutStartSec=1800`, and all carry the L-49 memory-thrash signature. None was the 600 s deadline. | The timeouts are closed by ING-2 S2/S3a plus the drop-in. The live problem is the post-S2 fixed cost: no-op runs spend 361–478 s of 600 s (p50 399, n=68). |
| "Recorder instrument set is fixed at its 09:00Z boot" | **False.** The in-session reload loop (`data.py:1223 _update_instruments`) subscribed all 30 09-27 markets at 15:00:15Z on 09-26. The venue listed them at 09:46:16–49Z. | Nautilus plus the adapter's native extension already refresh. The defect is the 6 h reload ceiling (`data.py:303`), which costs ~5 h 13 min of D+1 opening tape daily. |
| "breezy-k1-daily 11.4G" | The memory peak is pinned at 11.8–12G (`MemoryHigh=12G`). The growing number is **wall time**: 6 m 51 s (09-12) to 27 m 10 s (09-27), against 1800 s. | Timeout risk contained by 6c-0 (DONE). The retirement question goes to 6c-R. |

---

## 1. Goal & acceptance criteria (numbered, testable)

Goal state: the data spine runs unattended.
- Every scheduled run lands inside its budget.
- Every next-day market is captured within 15 min of listing.
- Every persistent failure mode reaches the alert webhook.

### 6a — discovery-pull timer (URGENT)
- **AC-6a-1** The 09-27 16:52Z run is timer-triggered. `breezy-discovery-pull.timer` `LastTriggerUSec` = `Sun 2026-09-27 16:52:xx UTC`, and the service `ExecMainStartTimestamp` is within 60 s of it.
- **AC-6a-2** That invocation's journal has no `Traceback` and no `ModuleNotFoundError`. It shows `Finished`, `Result=success`, `ExecMainStatus=0`.
- **AC-6a-3** Exactly one of `data/evidence/discovery_set_equality/2026-09-27.json` or that day's `no_pull.json` (with a reason) exists, with mtime ≥ 16:52Z.
- **AC-6a-4** No `breezy-study-failed@breezy-discovery-pull.service.service` invocation runs after 16:52Z.
- **AC-6a-5** A regression test runs each venv-python unit's ExecStart as the unit would: under its own `WorkingDirectory=`, with a scrubbed env, and with the repo root absent from `PYTHONPATH`. It is RED against the pre-2e109ec ExecStart and GREEN now.
- **AC-6a-6** Record the 16:52Z run's `Consumed … memory peak, … swap peak` line and CPU/wall. The 6a-2 bump rule is in §2.1.

### 6b — quote-ingest time budget (HIGH)
- **AC-6b-1** A no-op ingest run has `elapsed ≤ 60 s` at p90 over 24 h (today p90 = 455 s).
- **AC-6b-2** After the 09:00Z rotation, the rotated instance converts with `deferred_units=0 deferred_instances=0` within ≤ 2 consecutive runs.
- **AC-6b-3** For every instance, the memoized preflight report is field-for-field identical to a cold `scan_instance`. Proven by test, and by a host one-shot over all instances.
- **AC-6b-4** The deadline line gains `rss_peak_mb=<ru_maxrss//1024>` (integer, value-free).
- **AC-6b-5** Zero conversion-semantics change. The existing ingest suites stay green unmodified.
- **AC-6b-6 (C-4, blocking)**
  - (i) No path in `open_files` (as computed by `_open_files_for_instance` in `run_ingest`, `quote_tape_ingest_cli.py:1814-1823`, **before** the scan) is ever written to the memo, whether hit or miss. Such a file is always cold-inspected.
  - (ii) The memo key for a file is exactly the `os.stat_result` that `_inspect` used for that report: `(st_dev, st_ino, st_size, st_mtime_ns)`. It is never a second stat taken after the decode.
  - (iii) A lookup re-stats and hits only on an exact 4-tuple match.

### 6c — K1 daily (6c-0 DONE; 6c-R ruling; 6c-2 conditional)
- **AC-6c-0 [DONE 09-27 ~03:40Z]** The drop-in `zz-timeout-TEMPORARY.conf` sets `TimeoutStartSec=3600`. Verified `TimeoutStartUSec=1h`. Remaining proof: the 09-28 01:35Z run finishes `Result=success`.
  - **Removal condition:** remove the drop-in and daemon-reload on the **first** of these:
    - (a) the 6c-R ruling RETIRES K1: the drop-in goes with the unit;
    - (b) 6c-2 is merged and 3 consecutive nightly runs finish in < 1500 s (≥ 5 min headroom under the repo's 1800 s);
    - (c) 10-01T12:00Z passes with no ruling: then the ruling is overdue and is escalated in the peer loop, never extended silently.
  - Until removal it is named TEMPORARY in PROGRESS (L-29 containment).
- **AC-6c-R1** A written ruling `docs/evidence/RULING_k1_daily_disposition_2026-09-2x.md` exists. It is produced by the peer loop, never by the operator. It carries the §2.3 evidence table, applies the retirement test of `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` §1.3–§1.4 (`:39-54`; decision-table rows 1 "no consumer" and 2 "family dead by standing verdict", plus the E5/E13 hidden-dependency checks), and ends RETIRE or KEEP.
- **AC-6c-R2 (if RETIRE)**
  - `breezy-k1-daily.{timer,service}` are disabled and removed, along with `k1-daily-run.sh` and the drop-in.
  - `scripts/analysis/k1_cheap_open_settlement.py` is **kept** (a library: `wilson_interval`/`settles_yes`/`is_genuine_ask` are imported by ≥ 6 scripts).
  - `~/.local/share/breezy/k1/` is kept as evidence.
  - The unit-inventory tests are updated by one reviewed row each, never weakened.
- **AC-6c-2 (only if KEEP)**
  - The K1 report is byte-identical (modulo `generated_at`) on the same tape.
  - The dedupe-set peak is O(max rows per instrument), shown by a white-box counter.
  - The `read_all` transient is replaced by `read_feather_coalesced`.

### 6d — next-day market capture (HIGH)
- **AC-6d-1** On the first recorder boot after deploy (09-28 09:00Z rotation), the recorder logs `discovery reload cadence: operator override, 15 minute(s)` (`quote_tape_cli.py:263-268`). The live node's log keeps the derived cadence line (`clamped to the ceiling of 21600s` or a derived value).
- **AC-6d-2** Every D+1 slug listed at ~09:46Z is logged `subscribing … (new)` no later than listing + 15 min + 60 s.
- **AC-6d-3** On that day:
  - by listing + 20 min, `comm -23 <subscribed D+1 slugs> <order_book_depths/ D+1 dirs>` is empty (L-45 coverage count);
  - there are zero `max subscriptions per connection` and zero connection-refusal lines;
  - the recorder's peak `shards=` ≤ 12;
  - **reconnects/h on the new shards (the 10:00–16:50Z window, with no node) ≤ the 09-26 24 h baseline rate of 14/24 h ≈ 0.6/h, +1 allowed.** A breach is a rollback trigger.
- **AC-6d-4** Dropped (C-3).

### 6e — capital-flow timer (observation only)
- **AC-6e-1 [verified]** `NextElapseUSecRealtime=Sun 2026-09-27 17:30:00 UTC`; `LastTriggerUSec` is empty (the 09-26 21:52Z run was manual).
- **AC-6e-2** After 17:31Z on 09-27:
  - `LastTriggerUSec` reads 17:30:xx;
  - `ExecMainStartTimestamp` is within 60 s; `Result=success`, `ExecMainStatus=0`;
  - one `CAPITAL_FLOW_PULL status=OK`;
  - a new snapshot mtime in [17:30, 17:35]Z;
  - no `breezy-study-failed@` instance;
  - `breezy-portfolio-roi.service` starts after the pull's `ExecMainExitTimestamp`.

### 6f — deferral-stall alert (MED, after 6b)
- **AC-6f-1** Pending work deferred on ≥ 4 consecutive runs **and** ≥ 60 min makes the run exit **4** (`EXIT_DEFERRAL_STALLED`) on the crossing run. `OnFailure=` then delivers `study_unit_failed` via `breezy-study-failed@`.
- **AC-6f-2** Re-alert every 16th run while the stall persists (~4 h). Runs in between exit 0.
- **AC-6f-3** Below threshold → exit 0. `test_run_exits_zero_when_every_non_success_is_a_deferral` stays green, unmodified.
- **AC-6f-4 (C-5) Exit-3 interaction.** The streak machine is **independent of the exit code**; the exit code applies precedence 2 > 3 > 4 > 0.
  - (i) A run that exits 3 with pending deferrals still increments `consecutive_runs` (a failure is not progress).
  - (ii) If a stall alert is *due* in that run (crossing, or `runs_since_alert ≥ 16`), the run prints the `DEFERRAL_STALLED` line and sets `runs_since_alert=0`. The exit is still 3, so exactly one `OnFailure` webhook fires for the invocation and the stall line is in the same invocation's journal.
  - (iii) If no alert is due, `runs_since_alert` increments exactly as on an exit-0 run.
  - (iv) An exit-3 run with **no** pending deferrals resets the streak, exactly as exit 0 does.
- **AC-6f-5** "Pending" for a not-evaluated instance uses `_instance_has_pending_work`, which is true iff at least one feather file is **not** in any of these states:
  - blanket type-marked;
  - per-file-marked (`.converted-file-…`);
  - salvage-marked (`.salvaged-…`, `.salvage-unsupported-…`);
  - in `open_files`.
  The three stuck instances (Q3) therefore **never** count, and a fully converted instance never counts.
- **AC-6f-6** The streak file lives at `<catalog_root>/.ingest-deferral-streak-v1.json`: the catalog root, never under `live/` or an instance dir. It has a single writer (the ingest unit) and uses atomic replace.

---

## 2. Evidence / root cause (file:line)

### 2.1 6a — discovery pull
- 09-26 16:52:47Z: the timer run failed with `ModuleNotFoundError: No module named 'scripts'` (`scripts/analysis/discovery_venue_pull.py:29`) under the direct-file ExecStart. The unit then logged `Failed with result 'exit-code'`.
- 2e109ec changed `deploy/systemd/breezy-discovery-pull.service:67` to `-m`. The 17:29:46Z run was manual and succeeded. The timer path has not run the new ExecStart.
- Existing guard `tests/unit/test_discovery_pull_exec_import.py` has three gaps:
  - it hard-codes `cwd`;
  - it inherits the environment;
  - it covers one unit (`breezy-fee-evidence-pull.service` and the `*-run.sh` wrappers also exec by path; `k1_cheap_open_settlement.py:103` bare-imports a sibling).
- **C-7 memory evidence (verified 09-27):**
  - `systemctl --user show breezy-discovery-pull.service`: `MemoryHigh=134217728` (128M, unit `:31`), `MemoryMax=268435456` (256M, `:32`), `MemorySwapMax=infinity`, `TimeoutStartUSec=30min` (`:72`).
  - 09-26 journal, only the 17:29:50Z run has a `Consumed` line (the 16:52Z run died at import): `3.052s CPU over 3.192s wall, 128.8M memory peak, 129.9M memory swap peak`.
  - Reading: the cgroup hit `MemoryHigh` and reclaim pushed ~130M to swap, so reclaim **is** active on an import-only run. But CPU/wall = 0.96, so there was no measurable throttle stall on that run.
  - `memory.events high` for 09-26 is unrecoverable (the transient cgroup is gone after exit), so throttle counts cannot be verified.
  - **Recommendation: no bump before 16:52Z.** The 16:52Z proof is an import-path proof, and MemoryHigh cannot cause `ModuleNotFoundError`. The failure mode a bump would prevent (throttle stretching a ≤ 20-min poll past 30 min) is not evidenced. Changing the unit before the proof confounds it.
  - Rule for **6a-2** (after 16:52Z): apply a `MemoryHigh=224M` drop-in (MemoryMax 256M unchanged; `test_memory_max_is_at_most_256m` holds) **only if** the 16:52Z run shows either of:
    - (i) CPU/wall < 0.8;
    - (ii) wall time > 25 min.
  - A swap peak alone is already known and is **not** a trigger. Make it a repo unit edit plus test, not a hand drop-in, if applied.

### 2.2 6b — ingest budget
- Deadline series (n=68 since 09-26 08:07Z): elapsed min 361 / p50 399 / p90 455 / max 610 s. Runs > 600 s: 11:25Z, 19:40Z, 09-27 02:25Z and 02:40Z (24 instances deferred each).
- Mechanism:
  - `run_ingest` (`quote_tape_ingest_cli.py:1751`) short-circuits only on `_instance_is_fully_converted` (`:416-430`, called at `:1825`).
  - Everything else calls `scan_instance` (`:1851` → `feather_preflight.py:499-530`), which inspects every file through `_inspect` (`:379`) → `_scan_stream`, a full message-by-message decode, every 15 min. Measured throughput is ~52 MB/s; ~14 GB/run ≈ 270–320 s.
- Memory is page cache: the 02:30Z sample showed anon 148–150 MB, file 3.06–7.62 GB, `VmHWM` 311–315 MB.

#### 2.2.1 Answer to r1 Q3 — why 7f353f94 / 887d2005 / c230f4fc never become "fully converted"
Established from code plus on-disk markers (read-only `ls -A`, 09-27):
1. Each instance has truncated files, so `run_ingest` sends it down the **per-file path** `_ingest_instance_per_file` (`:1558`).
2. That path writes only **per-file** markers (`_mark_file_converted`, `:527`, `:1523`). The blanket `.converted-<type>` marker is written only by the whole-type native path (`:1226`) and the definitions path (`:1374`). No code **promotes** a dead type whose closed files are all per-file-marked to the blanket marker. The module docstring (`:205-216`, `:303-312`) says blanket is "safe once a type's group is known dead", but nothing ever acts on that for per-file-converted types.
3. `_instance_is_fully_converted` requires a blanket marker for every present type (`:423-429`). On disk the three instances carry `.converted-binary_option` only, plus 56–120 per-file markers per tick type and `.salvaged-*` markers. They therefore fail the short-circuit forever and are fully re-decoded every run.
4. Also, `has_unresolved_truncation = bool(truncated_to_salvage)` (`:1625`) does not exclude already-salvaged files, so the outcome is `skipped-truncated` on every run. This is consistent with the logged `skipped (N truncated…)`.

Data-risk reading: this is **hygiene, not a hidden conversion gap**, with one exception already on record. 7f353f94 holds one `.salvage-unsupported-tc-temp-nychigh-2026-09-05-lt79f…` marker. Those rows were **not landed** (unsupported Arrow wrangler, FU-7 6297d11, marked terminal and logged ERROR by `quote_tape_salvage.py:394-410`). That loss is known and pre-existing; the rescan loop does not recover it.

Named follow-up **6b-2 (LOW)**: a dead-instance promotion rule. When an instance is dead and every closed file of a type is per-file-marked or salvage-marked, write the blanket marker. This needs its own review because it widens when blanket markers appear. After the memo (6b), these instances cost only `stat` calls, so 6b-2 is not on the critical path. 6f does **not** depend on it (AC-6f-5 uses a marker-aware predicate).

### 2.3 6c — K1 (retirement ruling evidence, C-2)
| # | Fact | Citation |
|---|---|---|
| K-E1 | Standing verdict "**K1 DEAD at ask ≥2c**" | `docs/core/PROGRESS.md:30` |
| K-E2 | The ≤ 0.05 cell is **FAMILY_DEAD** (n=179, k=2, Wilson high 0.0398 < break-even 0.052850) | `~/.local/share/breezy/k1/k1_2026-09-27.md:1166` |
| K-E3 | The ≤ 0.01 cell: n=9 (09-27 report `:1163`) vs **359** needed; "The 0.01 tick is **effectively unrefutable** … a zero-YES refutation would take about a year" | `docs/evidence/k1_cheap_open_2026-09-01.md:237,242-245` |
| K-E4 | The driver declared a deadline, **2026-10-01T12:00Z**. The systemd wrapper has **no** deadline stop (`k1-daily-run.sh`, 81 lines; no deadline logic), so the unit runs forever past it unless ruled. | `~/.local/share/breezy/k1/k1_daily.log:1`; `deploy/systemd/k1-daily-run.sh` |
| K-E5 | K1 measures the "cheap open" of D+1 rungs, but the recorder's first D+1 observation is ~5 h 13 min after listing (6d). The "first genuine ask" folded is not the open, so even the live strata measure the wrong instant until 6d lands, and the retrospective tape can never be repaired. | §2.4 below; venue `startDate` 09:46Z vs subscribe 15:00:15Z on 09-26 |
| K-E6 | Cost: ~27 min wall and ~12G cgroup nightly, growing about 1.35 min/day (O(total tape) re-read, a global dedupe set) | journal `breezy-k1-daily` since 09-12 |
| K-E7 | The script is a **library**: `wilson_interval`, `settles_yes`, `is_genuine_ask` and `summarize_stratum` are imported by `cli_basis_setup_win_rate_study.py:73`, `cli_basis_offer_gate_scan.py:148`, `cli_basis_adverse_selection_probe.py:80`, `cli_basis_hourly_profile_study.py:115`, `cli_basis_offer_gate_settlement.py:89` and `k1_kalshi_prior.py:134`. Retiring the unit must not delete it (same shape as E5 in the 09-21 ruling). | `/usr/bin/grep` 09-27 |
| K-E8 | Consumer check (row 1): the only PROGRESS reference is the standing verdict (`:30`). No backlog row reads `k1_*.md`. The ruling must re-run the E11-style search and the E13-style hidden-dependency read of `k1-daily-run.sh` (only `:68` invokes Python per grep; the ruling confirms with a full read). | `docs/core/PROGRESS.md` |

Retirement test (`RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md:39-54`): row 2 (family dead by standing verdict) fires on K-E1/K-E2 for every cell ≥ 2c. The only live stratum (≤ 1c) is unrefutable in the remaining horizon (K-E3) and mis-measured (K-E5). Row 1 (no consumer) appears to fire (K-E8). Architect's expected outcome: **RETIRE** the unit, keep the script. The ruling, not this plan, decides.

### 2.4 6d — next-day capture
- `data.py:1223 _update_instruments` is the native-extension reload loop. Delay comes from `_next_reload_delay_secs` (`:1193`). **An explicit `instrument_reload_interval_mins` wins outright** (`data.py:1202-1204`: `override = self._venue_config.instrument_reload_interval_mins; if override is not None: return float(override) * 60.0`).
- That field is populated from the env var `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS` (`factories.py:145`, parsed with positive-integer validation at `:283-297`, passed at `:325`). The recorder logs which cadence is in force at boot (`quote_tape_cli.py:263-268`).
- **The capability already exists. No code is needed.** This is the null hypothesis holding twice (Nautilus reload pattern → adapter extension → existing override).
- Currently unset: `polymarket.env` has 0 occurrences of the variable name (count-only check; no values printed).
- Placement: `breezy-quote-tape.service` loads `EnvironmentFile=/home/jon/.config/breezy/polymarket.env` (`:81`), which the **trade supervisor also loads** (`breezy-trade-supervisor.service:102`). The override must therefore go in the recorder unit as `Environment=` (next to `:93`), **never** in `polymarket.env`, or the live node's cadence changes.
- Side effect of the override: the recorder stops targeting exact boundaries. Expired markets drop up to 15 min later than today, which is harmless for a recorder. The ceiling-clamp WARN disappears from the recorder (the derive path is bypassed), which is why r1's AC-6d-4 is moot.
- **Idle timeout correction:** `ws_idle_timeout_secs = 600` (`config.py:293`, raised from 60 s after 224 recorder closes on 09-10/11). A 15-min reload does not interact with it: the reload is REST discovery, and quiet-shard idle closes are governed by 600 s.
- **Connection count per API key (C-3).** Both processes load the same `polymarket.env`, so assume one key.
  - The recorder peaks at 12 shards (journal 09-26: `shards=1…12`, 12 at 15:00Z).
  - The node ran 6 shards on its 09-26 16:50Z boot (`breezy-trade-20260926T165018Z.log`: `shards=1…6`).
  - Combined peak = **18 concurrent connections**, already sustained daily from ~16:50Z (node boot) to the 09:00Z rotation. On 09-26 it drew **0** subscription/connection refusals (recorder journal 09-26 09:00Z–09-27 09:00Z; the 128 raw matches were all "book level(s) discarded" lines containing the digits 429; node log 0), and there were 14 recorder `reconnect` lines in 24 h.
  - Against the probe: `WS_CONCURRENT_CONNECTIONS_20260917T093016Z.probe.json` measured 12 concurrent connections with no refusal; the **ceiling was not located**. 18 is therefore above the only probe measurement, and it is observed-safe only by daily operation. LESSONS L-45 (`:1487`) keeps it an open question.
  - 6d does **not** raise the combined peak. It moves the recorder's 12-shard state earlier (~10:00Z instead of 15:00Z), into a window where the node is normally down (the supervisor cannot spawn 01:00–16:40Z), so the combined count there is 12, not 18. A mid-day node relaunch (window to 01:00Z) could reach 18 earlier in the day, which is the same peak as today.
- **D2 (listing-time prediction) rejected (C-3):**
  - it adds new logic for ≤ 15 min of benefit over the override;
  - the venue skips ~9% of station-days and listing time drifts;
  - it is exactly the "prediction as mechanism" the counterfactuals lesson warns against.

### 2.5 6e — capital-flow timer
Install timing, not a defect (enabled 21:52:24Z on 09-26, after the 17:30Z slot; `Persistent=true` catches up only slots since the stamp).

### 2.6 6f — deferral silence
`run()` exits 0 on any deferral by contract (`quote_tape_ingest_cli.py:2193-2200`). The only alert path is `OnFailure=` (`breezy-quote-tape-ingest.service:22`), and the notifier has no dedupe (`study_failure_notifier.py`). A deferral streak is silent. It is live now (09-27 02:25Z and 02:40Z, 24 instances each).

---

## 3. Options & trade-offs

### 6b
| Option | Verdict |
|---|---|
| Raise the 600 s budget / more chunking / split salvage | Rejected (r1 reasons unchanged: none touch the ~14 GB re-decode) |
| **Preflight memo keyed on `_inspect`'s own pre-scan stat; open files never memoized** | **Chosen** |
| Memo keyed on a post-decode stat | **Rejected (C-4).** A file that grows between `_inspect`'s stat and the decode's EOF gets a report describing N bytes under a key naming N+k. Or the reverse: a TRUNCATED-mid-write report is frozen under a key the closed file later matches if size and mtime coincide. Both can freeze a wrong status, which is a data-loss path (a file wrongly TRUNCATED gets salvaged instead of converted, or a wrongly INTACT one is converted short). |
| Memo includes open files, relying on the key changing | **Rejected (C-4).** A live file's mtime can be unchanged across a partial flush on coarse-mtime filesystems, and the rename-rotation window is exactly where `(ino, size, mtime)` can alias. Excluding `open_files` removes the class entirely; they are few (newest per type group), so the cost is negligible. |
| 6b-2 blanket-marker promotion | Deferred LOW (§2.2.1) |

### 6c
| Option | Verdict |
|---|---|
| C0 timeout 1800 → 3600 | **DONE** as a TEMPORARY drop-in (C-1) |
| **C1 retirement ruling** | **First** (C-2), via the peer loop, §2.3 |
| C2 per-instrument dedupe + coalesced read | Only if C1 = KEEP |
| C3 incremental fold cache | **Dropped** (C-2) |

### 6d
| Option | Verdict |
|---|---|
| N0 native Nautilus periodic reload | Holds, via the adapter's `_update_instruments` |
| **Existing env override, recorder unit only, 15 min** | **Chosen** (C-3): zero code |
| New per-role ceiling config field (r1 D1′) | **Dropped** (C-3): duplicates an existing override |
| Override in `polymarket.env` | Rejected: shared with the live node |
| D2 listing-time prediction | **Rejected** (C-3) |
| D3 move the rotation | Rejected (r1) |

Rate cost: 96 discovery GETs/day vs ~4 today, ≤ 4/h against a 6/min quota.

### 6f
F1 (in-process streak + exit 4) chosen, unchanged from r1. F2 (journal watcher) and F3 (freshness SLO) are not chosen; F3 is a named follow-up.

---

## 4. Architecture & data flow

- **6b.** Add an additive seam to `feather_preflight.py`:
  - `inspect_feather_file_with_stat(path) -> tuple[FeatherFileReport, os.stat_result]`;
  - `_inspect` is refactored to accept an optional pre-taken `stat` and return it. There is one stat call per inspection, as today.
  - `inspect_feather_file`, `scan_instance` and every existing caller are byte-for-byte unchanged in behaviour.
  - New `breezy/persistence/preflight_memo.py` provides `scan_instance_memoized(catalog_root, instance_id, subdirectory, *, open_files: frozenset[Path]) -> PreflightReport`. For each file in `iter_feather_files` order:
    - if `path in open_files`: cold `inspect_feather_file`, and **never** write it to the memo;
    - else: `st = path.stat()`. On a memo entry with an equal `(st_dev, st_ino, st_size, st_mtime_ns)`, reuse the cached report. Otherwise `(report, st0) = inspect_feather_file_with_stat(path)` and store under **st0's** tuple (the stat `_inspect` used), never `st`.
  - Assemble the `PreflightReport` in the same order. Rewrite `<instance_dir>/.preflight-memo-v1.json` atomically (tmp + `os.replace`) only if it changed. Drop entries for files that no longer exist.
  - A corrupt or unknown-version memo is scanned cold, with one WARN, then rewritten.
  - Call site: `run_ingest` `:1851` passes the already-computed `open_files` (`:1814-1823`).
- **6b concurrency statement (C-4).**
  - Ingest-vs-ingest exclusion rests on **systemd single-instance semantics** (a oneshot `breezy-quote-tape-ingest.service` cannot run twice concurrently) **plus the hand-run ban** (unit comment `:83-86`, L-50).
  - **No code enforces it.** The memo adds no lock, consistent with the existing marker files, which have the same stance.
  - Recorder-vs-ingest is safe by construction: the recorder never lists or writes dot-files, the memo is written with atomic replace, and the files the recorder can still write are exactly `open_files`, which are never memoized.
- **6b-4.** `run()` appends `rss_peak_mb` to the deadline line.
- **6c-R.** Peer loop → ruling doc. If RETIRE: an ops change (disable + remove the unit, timer, wrapper and drop-in; keep the script). If KEEP: 6c-2 as r1 §4 (instrument-grouped streaming, per-instrument `seen`, `read_feather_coalesced`).
- **6d.** One directive in `deploy/systemd/breezy-quote-tape.service`:
  `Environment=POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS=15`, with a comment citing this plan, `data.py:1202-1204`, and "never in polymarket.env (shared with the trade supervisor)".
  Flow: systemd env → `factories.py:283` → `PolymarketUSDataClientConfig.instrument_reload_interval_mins=15` → `data.py:1202` returns 900 s → `_update_instruments` reloads every 15 min → new slugs are subscribed through the existing pool.
- **6f.** New pure module `breezy/runtime/ingest_deferral_streak.py` (stdlib only):
  - State `{version, consecutive_runs, first_deferred_utc, runs_since_alert}` at `<catalog_root>/.ingest-deferral-streak-v1.json`.
  - `step(state, *, pending: bool, now) -> (new_state, alert_due: bool)` is independent of exit code.
  - `run()` computes `pending`:
    - any per-type/salvage `DEFERRED_DEADLINE`, **or**
    - any `"not evaluated"` instance where `_instance_has_pending_work(instance_dir, open_files)` is true (AC-6f-5).
  - If `alert_due`, print the value-free `DEFERRAL_STALLED runs=… age_s=… pending_units=…`.
  - Exit = max-precedence of {2, 3, 4 if alert_due, 0}. `_instance_has_pending_work` is a new helper next to `_instance_is_fully_converted`; the latter is unchanged.

---

## 5. File-by-file plan

| File | Slice | Change |
|---|---|---|
| `tests/unit/test_unit_execstart_imports.py` (new) | 6a | Parametrized ExecStart-as-unit import test (r1 spec). Keep `test_discovery_pull_exec_import.py`. |
| `tests/unit/test_run_wrapper_python_imports.py` (new, optional) | 6a | Same check for `*-run.sh` python invocations |
| `deploy/systemd/breezy-discovery-pull.service` + its test | 6a-2 (conditional, §2.1 rule, after 16:52Z) | `MemoryHigh=224M` |
| `src/breezy/persistence/feather_preflight.py` | 6b | Additive: `inspect_feather_file_with_stat`; `_inspect(path, *, collect, stat=None)` returns the stat it used. No behaviour change to existing public functions. |
| `src/breezy/persistence/preflight_memo.py` (new) | 6b | `scan_instance_memoized(..., open_files=...)`, `MEMO_FILENAME`, `MEMO_VERSION` |
| `src/breezy/runtime/quote_tape_ingest_cli.py` | 6b, then 6f | 6b: `:1851` → memoized with `open_files`; `rss_peak_mb`. 6f: `EXIT_DEFERRAL_STALLED=4`, `_instance_has_pending_work`, streak wiring, docstring exit table |
| `src/breezy/runtime/ingest_deferral_streak.py` (new) | 6f | Pure state machine + atomic JSON I/O |
| `deploy/systemd/breezy-quote-tape-ingest.service` | 6f | Comment only: exit contract 0/2/3/4 |
| `deploy/systemd/breezy-quote-tape.service` | 6d | + `Environment=POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS=15` (+ comment) |
| `tests/unit/test_quote_tape_unit_env.py` (new, or extend an existing unit-file test) | 6d | Pins the directive in the recorder unit, and its absence from `breezy-trade-supervisor.service` |
| `docs/evidence/RULING_k1_daily_disposition_2026-09-2x.md` (new, by the peer loop) | 6c-R | Ruling |
| K1 unit/timer/wrapper + inventory tests | 6c-R2 (if RETIRE) | Remove; one reviewed row per inventory pin |
| `scripts/analysis/tape_arrow_columns.py`, `k1_cheap_open_settlement.py` | 6c-2 (if KEEP) | As r1 |
| `deploy/systemd/README.md` | 6b, 6d, 6f, 6e | Memo file; exit 4; recorder override; "a timer enabled after its slot fires next day" |
| `docs/core/PROGRESS.md` ING-2 row | hand-off | Amendment text of §11.1 (the coordinator applies it) |

No Nautilus file, `.venv`, egress path, operator control, enablement or A1 halt is touched.

---

## 6. Test strategy (RED first)

### 6a
- `test_every_venv_python_execstart_imports_under_its_working_directory[breezy-discovery-pull.service]`: RED on the pre-2e109ec ExecStart fixture, GREEN now.
- `…[breezy-fee-evidence-pull.service]`: characterization, with mutation evidence (L-33).
- `test_execstart_env_excludes_repo_root_from_pythonpath`.
- `test_execstart_working_directory_is_honoured`.
- Edge: `%h` / `${VAR}` expansion.

### 6b
- `test_memo_report_equals_cold_scan_field_for_field`: intact, truncated, empty-file, empty-stream and unreadable fixtures via real writer paths (L-42).
- `test_memo_hit_performs_zero_stream_decodes`: RED today.
- `test_memo_invalidates_on_size_change` / `_on_mtime_change` / `_on_inode_change` / `_on_device_change`.
- **`test_live_open_file_never_memoized` (C-4):**
  - a file in `open_files` is cold-inspected on both of two runs (`_scan_stream` called twice);
  - its name never appears in the written memo JSON;
  - a previously memoized file that becomes open (re-opened fixture) is cold-inspected and **evicted** from the memo.
- **`test_memo_key_is_inspect_pre_scan_stat` (C-4):**
  - monkeypatch `_scan_stream` to append bytes to the file mid-decode (simulated growth);
  - assert the stored key equals the pre-decode stat (size N), not the post-decode size (N+k);
  - assert the next lookup (size N+k) **misses** and re-inspects.
- `test_inspect_feather_file_unchanged_by_stat_seam`: `inspect_feather_file` output is identical before and after the refactor across all fixture kinds.
- `test_memo_new_file_scanned_removed_file_dropped`; `test_corrupt_memo_falls_back_to_cold_scan_and_warns_once`; `test_unknown_memo_version_ignored`; `test_memo_write_is_atomic_and_skipped_when_unchanged`.
- `test_run_ingest_passes_open_files_to_memoized_scan_and_outcomes_unchanged`.
- `test_deadline_line_carries_rss_peak_mb_integer`.
- Host one-shot (deploy proof): memo vs cold for every instance, read-only, `systemd-run --user -p MemoryMax=2G`, quiet window.

### 6c
- 6c-R: no code tests. The ruling is peer-reviewed.
- If RETIRE: the inventory tests change by one reviewed row each, and a new test asserts the script still imports as a library.
- If KEEP: the r1 6c-2 tests (population identical, bounded `peak_seen`, coalesced-reader spy, cross-source dedupe, preflight counts unchanged, truncated counted as failure).

### 6d
- `test_recorder_unit_sets_discovery_reload_interval_15`: parses `breezy-quote-tape.service` `Environment=`. RED before the edit.
- `test_trade_supervisor_unit_does_not_set_discovery_reload_interval`: guards the node cadence.
- Existing `factories` parsing tests and `test_polymarket_us_autonomy_g19.py:332-363` stay green unmodified (no code change).
- No `polymarket.env` test: the file is host config, outside the repo. The deploy check is a count-only grep (0).

### 6f
- `test_streak_below_threshold_exits_zero`; `test_fourth_consecutive_pending_deferral_after_60min_exits_4`; `test_three_runs_or_under_60min_do_not_alert`.
- `test_realert_every_16_runs_while_stalled`; `test_runs_between_realerts_exit_zero`; `test_streak_resets_on_a_run_with_no_pending_deferral`.
- **C-5:**
  - `test_exit3_run_with_pending_increments_streak`;
  - `test_exit3_run_with_due_stall_prints_line_resets_runs_since_alert_and_exits_3`;
  - `test_exit3_run_not_due_increments_runs_since_alert`;
  - `test_exit3_run_without_pending_resets_streak`.
- **AC-6f-5:**
  - `test_not_evaluated_per_file_and_salvage_marked_instance_never_counts` (fixture mirrors the 7f353f94 marker layout: `.converted-binary_option`, per-file markers, `.salvaged-*`, one `.salvage-unsupported-*`);
  - `test_not_evaluated_fully_converted_instance_never_counts`;
  - `test_not_evaluated_instance_with_unmarked_closed_file_counts`.
- `test_streak_file_lives_at_catalog_root_not_live`; `test_stall_line_is_value_free`; `test_corrupt_streak_file_resets_and_warns`; `test_dry_run_never_touches_streak_file`.
- Existing `test_run_exits_zero_when_every_non_success_is_a_deferral`: green, unmodified.

Gate per slice: `scripts/ci/run_tests_no_egress.sh` with `PYTHONPATH=<wt>/src`, `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`, basetemp `/home/jon/.cache/breezy-gate/…`, `-p LimitNOFILE=524288` when unit-launched; then `lint-imports`. Full gate after every merge (L-43).

---

## 7. Execution order & parallelism

| When (UTC, 09-27 → 09-28) | Action | Parallel? |
|---|---|---|
| Now | ING-2 amendment (§11.1) to the coordinator. The sampler is armed before 09:15Z. | yes |
| Now → 08:45Z 09-28 | 6d (worktree D): one line + 2 tests → merge → `systemctl --user daemon-reload` (no restart) | yes |
| Now → any inactive ingest gap, ideally before 09-28 09:00Z | 6b (worktree B) → merge in a gap | yes (∥ A, D) |
| After 6b merge | 6f (worktree B′, rebased on 6b); serial, same file | serial |
| Now → 16:52Z | 6a tests (worktree A). **No unit change.** | yes |
| 16:52Z / 17:30Z | Observe 6a / 6e | — |
| After 16:52Z | 6a-2 only if the §2.1 rule fires | — |
| Now → before 10-01T12:00Z | 6c-R peer loop → ruling → R2 (retire) or 6c-2 (keep) | yes |
| 09-28 01:35Z | 6c-0 proof (`Result=success` under the 1 h drop-in) | — |

Routing: `tdd-guide` seeded with python-testing/python-patterns implements; `python-reviewer` reviews independently; the 6c-R ruling goes through the architect + prediction-market-reviewer peer loop. Each worktree has its own scratchpad.

---

## 8. Deploy & verification

- **6a.** At ≥ 16:53Z:
  - `systemctl --user show breezy-discovery-pull.timer -p LastTriggerUSec`;
  - `… .service -p ExecMainStartTimestamp,Result,ExecMainStatus`;
  - `journalctl --user -u breezy-discovery-pull --since '2026-09-27 16:50'` (no Traceback; Finished; the Consumed line → CPU/wall);
  - `ls --time-style=full-iso data/evidence/discovery_set_equality/`;
  - `systemctl --user list-units --all 'breezy-study-failed@*'`.
- **6b.** Merge when `ActiveState=inactive` and the next `*:0/15` tick is ≥ 3 min away.
  - Run 1 builds memos cold (~400 s). Run 2: `elapsed ≤ 60`, `rss_peak_mb` present.
  - Host one-shot: memo == cold for every instance.
  - Rotation run: rotated instance converted, deferral 0 within ≤ 2 runs.
  - Spot-check that no `open_files` path appears in the live instance's memo: `python -c` reads the JSON keys against the newest file per type group (value-free).
- **6c.**
  - 6c-0: the 09-28 01:35Z run shows `Result=success` and a new `k1_daily.log` line.
  - 6c-R2: `systemctl --user list-timers` has no `breezy-k1-daily`; `DropInPaths` is gone; the script imports.
  - 6c-2 (keep): report equality + a Stage-0 anon sample.
- **6d.**
  - Deploy = merge + `systemctl --user daemon-reload` before 08:45Z 09-28. The 09:00Z rotation `try-restart` picks it up. **Never** restart the recorder ad hoc.
  - Pre-rotation check: `systemctl --user show breezy-quote-tape -p Environment` lists the variable, and `systemctl --user show breezy-trade-supervisor -p Environment` does **not** (names only; values are not secrets, but print only this one name).
  - 09-28 proof:
    - the boot line `operator override, 15 minute(s)`;
    - `subscribing tc-temp-*-2026-09-29-* (new)` ≤ listing + 16 min;
    - peak `shards=12`;
    - 0 refusal lines;
    - L-45 `comm -23` empty by listing + 20 min;
    - `reconnect` count 10:00–16:50Z ≤ 5 (0.6/h × 6.8 h + 1);
    - the node's next spawn still shows its derived/21600 s line.
  - Rollback: remove the line, daemon-reload; live at the next rotation.
- **6e.** Per AC-6e-2. Record "fired on schedule" in PROGRESS.
- **6f.**
  - Scratch catalog positive control (never the production root): 4 runs, pinned clock, `--deadline-seconds 1` → exit 4 + the stall line.
  - An exit-3 + stall fixture run → exit 3 + the stall line.
  - Production: `DEFERRAL_STALLED` stays absent while 6b holds the budget.

---

## 9. Risk register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | Memo freezes a wrong status for a mid-write file | VL (after C-4) | H | `open_files` never memoized; key = `_inspect`'s own pre-scan stat 4-tuple; growth-during-decode test; memo versioned |
| R2 | Memo write races the recorder in the live dir | L | M | Dot-file, atomic replace; the recorder never lists dot-files; open files excluded |
| R3 | Two ingests run concurrently and interleave memo/streak writes | L | M | systemd oneshot single-instance + hand-run ban (L-50). **Not code-enforced.** Stated explicitly; atomic replace bounds the damage to one lost update. |
| R4 | The override leaks to the live node | — | — | `Environment=` in the recorder unit only; a test pins its absence from the supervisor; never in `polymarket.env` |
| R5 | Per-key connection ceiling exceeded | L | H | 6d does not raise the 18-connection combined peak (§2.4); 18 > the probe's 12 is already daily-sustained with 0 refusals; AC-6d-3 refusal + reconnects/h rollback trigger |
| R6 | 6f false stall on the 3 stuck instances | M (without the fix) → VL | M | AC-6f-5 marker-aware predicate + fixture mirroring 7f353f94 |
| R7 | 6f alert storm | L | M | Edge-triggered + 16-run re-arm; exit-3 interplay specified |
| R8 | K1 drop-in outlives its purpose | M | L | Removal condition (AC-6c-0) + TEMPORARY tag in PROGRESS; 10-01T12:00Z escalation |
| R9 | The K1 retirement loses a live measurement | L | M | The peer ruling decides; K-E3/K-E5 show the ≤1c stratum is unrefutable and mis-timed; the script and history are kept |
| R10 | 6a-2 confounds the proof | — | — | Not applied before 16:52Z; conditional rule |
| R11 | A fixture writes to the production catalog | L | H | `tmp_path`/basetemp only; scratch root for the 6f control |

---

## 10. LESSONS / invariant compliance

- **Nautilus immutable (L-1, L-11).** 6d is now zero-code: it uses an existing override on the adapter's native reload extension. 6b's seam is in a Breezy module. No Nautilus edit.
- **L-10 / L-32.** Brief premises corrected with artifacts. The C-4 data-loss path is closed by construction, not by argument.
- **L-29.** The K1 drop-in and ING-2 drop-in are named TEMPORARY, with explicit removal tests. **L-49**: triage by CPU/wall + `memory.stat` anon vs file (ING-2 amendment). **L-31**: K1 dedupe is per instrument, if kept.
- **L-45.** Coverage count, connection count vs probe stated, unmeasured ceiling kept open.
- **L-50.** Single writer, atomic replace, hand-run ban; the concurrency stance is stated as not code-enforced.
- **L-42 / L-33 / L-43 / L-51.** Real writer paths; mutation evidence; full gate per merge; no installer in worktrees.
- `allow_short` untouched. No safety/settlement/contract/NO-SEND test weakened. Exit contract widened by one reviewed code (4). Inventory pins change one reviewed row at a time (6c-R2). No operator cap read or assigned. Enablement and the A1 halt untouched. The node is never killed; the recorder deploys only via rotation.

---

## 11. Dependencies

### 11.1 ING-2 row amendment (hand-off, blocking — coordinator applies to the PROGRESS ING-2 row)
> **AMENDMENT (EDGE-6 r2, 2026-09-27):** the removal criterion "if its peak ≪ 12G" is **withdrawn**. cgroup `memory.peak` and the journal "memory peak" count page cache: the 09-27 02:30Z run showed anon ~150 MB vs file 3–7.6 GB. The deciding run is the **post-rotation conversion run in 09:15–09:45Z** (the first run whose journal shows `ingested …` rows for the rotated instance). A no-op run is not evidence. Remove `zz-memory-containment-TEMPORARY.conf` (12G/14G) + daemon-reload **only if ALL hold** for that run:
> (a) sampled `memory.stat anon` peak ≤ 2G, or `rss_peak_mb` ≤ 2048 once 6b-4 is live;
> (b) CPU/wall ≥ 0.8 (`CPUUsageNSec` / (`ExecMainExitTimestamp` − `ExecMainStartTimestamp`));
> (c) `memory.events high` grows by < 1 per second of wall (Δhigh / wall_s < 1).
> If any fails, keep the drop-in and record the numbers.

**Sampling procedure** (read-only, launched before 09:14Z as a durable transient unit):
1. `systemd-run --user --unit=ing2-sampler-20260927 -p MemoryMax=64M /bin/bash -c '<loop>'`. The loop:
   - waits until `systemctl --user show breezy-quote-tape-ingest -p ActiveState --value` ∈ {active, activating} for the first run starting ≥ 09:15Z;
   - resolves `CG=/sys/fs/cgroup$(systemctl --user show breezy-quote-tape-ingest -p ControlGroup --value)`;
   - records `high` from `$CG/memory.events` at start;
   - every 2 s appends `epoch anon file` (from `$CG/memory.stat`) and the current `high` to `~/.cache/breezy-ing2/sample-20260927.tsv`;
   - stops when `ActiveState` ∉ {active, activating}, then records `CPUUsageNSec`, `ExecMainStartTimestampMonotonic`, `ExecMainExitTimestampMonotonic` and `Result` from `systemctl --user show`.
2. If that run converted nothing (all `skipped-already-converted`), re-arm for the next tick up to 09:45Z. If none converts, the verdict is "no evidence", and the procedure repeats at 09-28 09:15Z.
3. Compute (a) max anon, (b) CPU/wall, (c) (high_end − high_start)/wall_s. Record the three numbers and the verdict in PROGRESS. No values other than these counts.

Sampling at 2 s may miss a sub-2 s anon spike. `rss_peak_mb` (6b-4) closes that gap once live; until then (a) is stated as "sampled".

- The 6b rotation proof and ING-2's observation may be the same run; record once, cross-reference.
- **AUD-02** owns discovery content (6a = run proof only). **FU-13b** owns capital-flow content (6e = schedule proof). **FU-7** (6297d11) owns the salvage-unsupported terminal marker referenced in §2.2.1.
- **EDGE items:** no hard dependency on EDGE-1, EDGE-3, EDGE-4 or EDGE-5. Soft dependencies:
  - EDGE-4 and EDGE-5 consume tape completeness (6d/6b/6f).
  - Any EDGE item using D+1 "open" statistics must note the pre-6d ~5 h capture lag (K-E5).

---

## 12. Confidence self-assessment & unknowns

| Slice | Confidence | Main unknown |
|---|---|---|
| 6a | HIGH | Whether the node spawns at 16:50Z (json vs `no_pull.json`, either proves the import). Throttle during a 20-min poll (6a-2 rule decides after). |
| 6b | HIGH on cause and the C-4 fix; MED-HIGH on ≤ 60 s | Per-15-min cost of newly closed files; seam refactor must keep `inspect_feather_file` byte-identical (tested) |
| 6c | HIGH that the ruling is well-posed; outcome belongs to the peer loop | Whether any off-repo consumer reads `k1_*.md` (K-E8 search in the ruling) |
| 6d | HIGH | Per-key connection ceiling unlocated (18 observed-safe daily; probe measured 12) |
| 6e | HIGH | Host uptime at 17:30Z |
| 6f | HIGH | Thresholds (4 / 60 min / 16) are Breezy policy; revisit after 2 weeks |
| ING-2 amendment | MED-HIGH | Whether a converting run lands in 09:15–09:45Z (fallback: 09-28) |

Open questions for the peer loop (not the operator):
- Q1: 6c-R — RETIRE vs KEEP (architect's expectation: RETIRE the unit, keep the script).
- Q2: 6b-2 — should blanket-marker promotion for dead per-file-converted types be scheduled, given it also shortens every future truncated instance's life in the rescan set?

## r2 final amendment (coordinator, round-2 merge). BINDING

Round-2: architect APPROVE, with two conditions for the implementer brief. Round 1: python APPROVE. A python confirmation of r2 is in flight; any blocker it raises is appended below. Otherwise: **READY**.

- **AM-1 (6f, not-evaluated instances).** Instances recorded as "not evaluated" at `quote_tape_ingest_cli.py:1805` are recorded before `open_files` exists (`:1815`). The 6f pending predicate must call `_open_files_for_instance` itself for those instances.
- **AM-2 (6f, salvage deferral).** A salvage deferral reports outcome `skipped-truncated`, because the truncation check (`:1625`, `:1680`) runs before the deferral check (`:1692`). The pending test must read `InstanceIngestResult.salvage_deferred` (`:1713`), NOT the outcome string. Otherwise an instance deferred every run is a stall nobody reports. RED test: `test_salvage_deferred_counts_pending`.
- **AM-3 (6d, deploy gate).** systemd `EnvironmentFile=` beats `Environment=`. Keep the count-only check that `polymarket.env` holds 0 occurrences of `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS` as a deploy gate. After the 09:00Z rotation, verify the recorder's boot log line shows the 15-min override.
- **AM-4 (6d).** 18 connections per key is a lower bound (markets pool shards 1..6 only; execution-side WS not located). 6d does not raise the peak, so no HOLD.
- **Python r2 confirmation: APPROVE** (scores 9-10; the 7f353f94 fixture and the 6d zero-code claim were verified on disk). Citation fix: the 6b call site to replace is `scan_instance(...)` at `quote_tape_ingest_cli.py:1853`, not `:1851` (`deadline.note_scan()`). **Status: READY.**
