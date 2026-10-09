# AUT-6 WP3 verify-first, S1 slice (2026-10-08)

Read-only `systemctl --user` / `journalctl --user` only. Nothing was reset, started or stopped.

## Failed-unit census (`systemctl --user list-units --failed --all --plain --no-legend`, ~20:50Z)

One unit: `breezy-autonomy-alert-redeliver.service` (failed, exit-code). The transients named in plan
§3.8 (`fq-halt-20261005`, `breezy-parity-mem-1d/7d`, `run-p814078-i21773018`,
`breezy-replay-backfill-0929`) are `LoadState=not-found` now: they were reset before this slice
started, so their `InvocationID` can no longer be read. `breezy-portfolio-roi` and
`breezy-fee-evidence-pull` are `inactive/Result=success` with `ExecMainStatus=1` retained (reset
after their failure). `breezy-discovery-pull` last run 20:09:50Z finished (WP3b).

## F2: is `InvocationID` non-empty on a failed unit?

`systemctl --user show -p InvocationID,Result,InactiveEnterTimestamp breezy-autonomy-alert-redeliver.service`:

```
InactiveEnterTimestamp=Thu 2026-10-08 20:10:58 UTC
InvocationID=8aa93b559c3846f087ca594a7b0985b3
Result=exit-code
```

Result: **PASS** (non-empty). Cross-check: the journal entries of that run carry
`USER_INVOCATION_ID=8aa93b559c3846f087ca594a7b0985b3` and `USER_UNIT=breezy-autonomy-alert-redeliver.service`
(`journalctl --user -o json`), so the property joins to the journal on `USER_INVOCATION_ID`
(the journal field is `USER_INVOCATION_ID`, not `_SYSTEMD_INVOCATION_ID`/`INVOCATION_ID`, for user
units logged by the manager).

Deviation from the brief: only ONE failed unit remained, so the planned second sample (a failed transient) is
unobtainable. The transients were gone before this verify-first ran. The plan fallback
(unit, InactiveEnterTimestamp) is therefore not exercised; it stays in the design for the
case of an empty id.
Not a STOP.

## V-6 (E-7e form), S2 slice, ~22:00Z 2026-10-08

Read-only: `systemctl --user show|list-units|list-timers`, `journalctl --user -o json`, `/proc/<pid>/status`.
Nothing was reset, started or stopped. Probe: a provisional health row (`network=none`, `host_proc` with
`E7A_R2_PROC`, binds `evidence/unit_health`, `derived/verdicts`, `evidence/alerts`, `cache/aut6_health_bus`,
four bus reads, budget 15) run through the real `build_bwrap_argv` + `bwrap` (no `--unshare-pid`, read-only
root, credentials tmpfs, `--tmpfs /run`) by `tests/support/bwrap_harness.run_in_row`. The snapshot was taken
outside by `write_bus_snapshot` (real `systemctl`, real bus) and consumed inside by `read_bus_snapshot`.
Outside reads ran immediately after the snapshot; `Memory*` keys are dropped from the `show` comparison
(they move between two reads), the timers comparison keys on the last two columns.

```
snapshot_writer_rc 0
node/supervisor pids [274295, 1037914]
child rc 0

INSIDE systemctl: [1, '', 'Failed to connect to user scope bus via local transport: No such file or directory\n']
read units_show: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=4695 bytes_in=4695
read failed_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=0 bytes_in=0
read timers_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=4719 bytes_in=4719
read run_transient: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=0 bytes_in=0
journal --until parsed-equal (key order is randomised per process): True rc 0 0 lines 5
journal last-5 (live, may drift) parsed-equal: True lines 5 5
proc 274295 ['Name:\tbreezy-trade-su', 'Umask:\t0077', 'State:\tS (sleeping)'] True
proc 1037914 ['Name:\tbreezy-trade', 'Umask:\t0077', 'State:\tS (sleeping)'] True
failed units outside: 
run_transient outside rc 0 inside rc 0
```

Result: **PASS, no mismatch.**
- In-row `systemctl --user show` fails (rc 1, "Failed to connect to user scope bus"), as E-7e(f) expects.
- The snapshot taken outside equals the outside reads for `show -p <set> -- 'breezy-*'`, `list-units --failed`,
  `list-timers` and `RUN_TRANSIENT_SHOW_ARGV` (rc 0 each).
- `journalctl --user -o json -n 5` works in-row and returns the same entries as outside, both with a fixed
  `--until` and live (compared parsed: journalctl randomises JSON key order per process, so raw bytes differ).
- `/proc/274295/status` and `/proc/1037914/status` (the supervisor and its node child under
  `breezy-trade-supervisor`, from `systemd-cgls --user-unit`) are readable in-row, `VmRSS` present.

Caveat: the failed-unit list and the `run-*` transient read were both empty at probe time, so their equality
is true but trivial; the handoff mechanics for non-empty output are pinned by the ARCH bus-handoff tests.

## V-6 re-run with the final argv and a positive control (review S2), ~21:40Z 2026-10-08

Final `units_show` argv (shipped row): `show -p <25 properties incl. MainPID,UnitFileState,LoadState> -- 'breezy-*' 'us-source-collector@*'`.
Two scratch failing units were created: `systemd-run --user --unit=claude-aut6-v6-fail /bin/false`
(InvocationID `eef3b89a14554e52b69214ba39bb3d26`) and an unnamed `systemd-run --user /bin/false`
(`run-p2307185-i44246311.service`, InvocationID `6c50741a17fb41e99638246fa039b529`); both `Result=exit-code`
(F2 second sample: InvocationID is non-empty on a failed unit and on a failed `run-*` transient).

```
snapshot_writer_rc 0
node/supervisor pids [274295, 1037914]
child rc 0

INSIDE systemctl: [1, '', 'Failed to connect to user scope bus via local transport: No such file or directory\n']
read units_show: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=20239 bytes_in=20239
read failed_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=269 bytes_in=269
read timers_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=4719 bytes_in=4719
read run_transient: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=341 bytes_in=341
journal --until parsed-equal (key order is randomised per process): True rc 0 0 lines 5
journal last-5 (live, may drift) parsed-equal: True lines 5 5
proc 274295 ['Name:\tbreezy-trade-su', 'Umask:\t0077', 'State:\tS (sleeping)'] True
proc 1037914 ['Name:\tbreezy-trade', 'Umask:\t0077', 'State:\tS (sleeping)'] True
failed units outside: claude-aut6-v6-fail.service     loaded failed failed [systemd-run] /bin/false
run-p2307185-i44246311.service  loaded failed failed [systemd-run] /bin/false
us-source-collector@mos.service loaded failed failed Breezy F13-C1 US-source collector, one cycle for source mos
run_transient outside rc 0 inside rc 0
COUNTS Id= blocks in units_show (outside)= 38  inside= 38  list-units --all rows= 91
failed_list inside:
claude-aut6-v6-fail.service     loaded failed failed [systemd-run] /bin/false
run-p2307185-i44246311.service  loaded failed failed [systemd-run] /bin/false
us-source-collector@mos.service loaded failed failed Breezy F13-C1 US-source collector, one cycle for source mos

run_transient inside:
Id=run-p2307185-i44246311.service
Description=[systemd-run] /bin/false
Transient=yes
InvocationID=6c50741a17fb41e99638246fa039b529
Result=exit-code
ExecStart={ path=/bin/false ; argv[]=/bin/false ; ignore_errors=no ; start_time=[Thu 2026-10-08 21:40:01 UTC] ; stop_time=[Thu 2026-10-08 21:40:01 UTC] ; pid=2307187 ; code=exited ; status=1 }
```

Equality: PASS. With both scratch units present, the snapshot equals the outside reads for all four reads
(`failed_list` 269 bytes, `run_transient` 341 bytes carrying the transient's InvocationID), in-row
`systemctl` fails, journalctl and `/proc/<pid>/status` work.

**Count check: MISMATCH.** `Id=` blocks in `units_show`: 38 (36 distinct units; the snapshot and the outside
read agree). `systemctl --user list-units --all 'breezy-*' 'us-source-collector@*'`: 91 rows (55 services more).
The 36 equal exactly `list-units` WITHOUT `--all` (active/activating/failed); `show -- <glob>` does not return
loaded-but-inactive (dead) units, e.g. `breezy-asos-refresh.service` (LoadState=loaded, inactive/dead). Failed units
ARE included (`us-source-collector@mos.service` appears twice, `claude-aut6-v6-fail` is outside the glob by name).
Per the S2 review rule a mismatch stops the slice: the glob read does not see inactive oneshots' last
`Result`/`ExecMainStatus`/`NRestarts`. Not resolved here.

Cleanup: `systemctl --user reset-failed claude-aut6-v6-fail.service run-p2307185-i44246311.service` (rc 0, journaled
via logger tag `claude-aut6`). Only those two; `us-source-collector@mos.service` (pre-existing failure) and every
`breezy-*` unit were not touched.

### Coordinator ruling R-S2-1

The `show` glob intentionally covers loaded active/activating/failed units (property detail: Result, ExecMainStatus, InvocationID, NRestarts, MainPID, MemoryPeak…) — that is what the pass needs detail for (a failed oneshot stays failed and is included; fail-then-succeed between passes is caught by the journal cursor per plan). Inventory completeness comes from TWO added fixed reads in the health row's bus_reads: (1) `list-units --all --plain --no-legend --full 'breezy-*' 'us-source-collector@*'` (load/active/sub for all loaded units → 91 today); (2) `list-unit-files --plain --no-legend --full 'breezy-*' 'us-source-collector@*'` (UnitFileState incl. not-loaded units → enablement for #28 and X-8 not-found/broken-link). Keep the read budget at 15 s total; measure the snapshot wall time and record it. Then re-run V-6: snapshot == outside for all six reads; positive control again with the two failing scratch units present (they must appear in the failed read and in list-units --all); count check now = `list-units --all` rows in snapshot vs outside (must be equal; mismatch = STOP). Reset-failed only the scratch units.

### V-6 re-run, six reads, ~22:00Z 2026-10-08

Both inventory argvs carry `--` before the patterns (the table grammar requires it); the grammar widened by the
verb `list-unit-files` and the bare option `--full`, one row each. Scratch failing units: `claude-aut6-v6-fail`
(InvocationID 91ff289781434ddbb89d26eca5dd3217) and `run-p2328651-i44270474` (2b7beb97166749a2bd7b8f69f01de60e).

```
snapshot_writer_rc 0 WALL_S 0.094
node/supervisor pids [274295, 1037914]
child rc 0

INSIDE systemctl: [1, '', 'Failed to connect to user scope bus via local transport: No such file or directory\n']
read units_show: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=18353 bytes_in=18353
read failed_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=154 bytes_in=154
read units_inventory: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=15463 bytes_in=15463
read unit_files_inventory: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=3691 bytes_in=3691
read timers_list: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=4719 bytes_in=4719
read run_transient: outside_rc=0 inside_rc=0 equal_normalised=True bytes_out=341 bytes_in=341
journal --until parsed-equal (key order is randomised per process): True rc 0 0 lines 5
journal last-5 (live, may drift) parsed-equal: True lines 5 5
proc 274295 ['Name:\tbreezy-trade-su', 'Umask:\t0077', 'State:\tS (sleeping)'] True
proc 1037914 ['Name:\tbreezy-trade', 'Umask:\t0077', 'State:\tS (sleeping)'] True
failed units outside: claude-aut6-v6-fail.service    loaded failed failed [systemd-run] /bin/false
run-p2328651-i44270474.service loaded failed failed [systemd-run] /bin/false
run_transient outside rc 0 inside rc 0
COUNTS list-units --all rows snapshot= 90  outside= 90  | list-unit-files rows snapshot= 61  outside= 61  | units_show Id= blocks= 35
scratch claude-aut6-v6-fail in failed_list: True in units_inventory: False
scratch run-p in failed_list: True in units_inventory: False
rc per read inside: {'units_show': 0, 'failed_list': 0, 'units_inventory': 0, 'unit_files_inventory': 0, 'timers_list': 0, 'run_transient': 0}
```

Result: **PASS.** Snapshot == outside for all six reads (rc 0 each); in-row `systemctl` fails; journalctl and
`/proc/<pid>/status` work. Count check: `list-units --all` rows snapshot 90 = outside 90 (91 a little earlier;
`us-source-collector@mos.service`'s failure was reset by someone else in between); `list-unit-files` rows 61 = 61;
`units_show` 35 `Id=` blocks (active/activating/failed only, as ruled). **Snapshot wall time: 0.094 s** for all six
reads (budget 15 s).
Both scratch units appear in the failed read. They do NOT appear in the two inventory reads: those are patterned
to `breezy-*` and `us-source-collector@*` by design and the scratch names (`claude-*`, `run-*`) match neither;
the transient is carried by the `run_transient` read instead.
Cleanup: `reset-failed` of those two scratch units only (rc 0, logger tag `claude-aut6`).

## F6: wall time of a full health pass (S6 slice, 2026-10-09 ~06:00-06:50Z)

Requirement (plan r15 WP3 verify-first F6): p99 wall time of a full pass over >= 20 manual runs <= 90 s, else the
reads are batched before the timer is enabled. Nothing was enabled, started or linked; the timer stays off.

**Method.** Each run is its own transient unit (`systemd-run --user --wait --collect --unit=claude-aut6-f6-<n>`), so
`INVOCATION_ID` and the cgroup are real. Inside it, per pass: (1) `write_bus_snapshot` for the health row with the
real home and data root (the unsandboxed pre line: the six fixed `systemctl --user` reads), then (2) the CLI
`autonomy_health_cli --dry-run` inside the health row's real `bwrap` argv (`tests/support/bwrap_harness.run_in_row`:
`build_bwrap_argv`, read-only root, `--tmpfs` home and `/tmp`, no network, host `/proc`, the four real binds). The
worktree code was imported through `PYTHONPATH`. `--dry-run` reads everything a real pass reads (snapshot, journal,
`git worktree list`, `/proc`, node logs, meminfo, the fold) and writes only to a scratch copy of
`evidence/unit_health` that it deletes; its summary line and its would-be findings are printed. The driver is not
committed (scratchpad); the four bind sources and `cache/aut6_health_bus` were created empty on the live root by the
unit's own `install -d` pre line (no content written there).

**Deviation.** The unit's real `ExecStart` chain through `deploy/systemd/breezy-autonomy-bwrap` cannot be driven by a
transient unit: the wrapper refuses it (`refused: unit_not_in_row`, exit 78) because the cgroup leaf must be
`breezy-autonomy-health.service`. That guard was not bypassed; the harness route above is the one the S2 V-6 probes
used. Not measured: systemd's own unit start and stop around the three commands (milliseconds on a oneshot).

| batch | n | p50 | p99 | max | min | non-zero exits |
|---|---|---|---|---|---|---|
| A, before the pin, per pass (snapshot + row) | 22 | 2.27 s | 2.31 s | 2.31 s | 1.20 s | 0 |
| A, outer `systemd-run --wait` wall | 22 | 2.69 s | 2.74 s | 2.74 s | 1.43 s | 0 |
| B, pin set and verified, per pass | 22 | 2.29 s | 2.37 s | 2.37 s | 1.52 s | 0 |
| B, outer `systemd-run --wait` wall | 22 | 2.70 s | 2.79 s | 2.79 s | 1.72 s | 0 |

Split: snapshot 0.21-0.33 s; row 0.97-2.01 s (the pass itself reports `wall_s=0.39-0.67`; the rest is bwrap setup,
interpreter start and the import closure). **Result: PASS.** p99 2.4 s against the 90 s requirement (and the 110 s
`timeout`), a factor of about 38 inside it; no batching of reads is needed. The dry pass does the same writes into
its scratch copy as a real pass would (54 class records, outbox entries, heartbeat, rollups), so the figure includes
them; it does not include a real fsync-to-live-root difference (same filesystem, same calls).

### What the first real pass would find (dry-run on the real snapshot, 2026-10-09 ~06:50Z)

`AUTONOMY_HEALTH pass_result=UNKNOWN failed_units=0 new_failures=54 foreign_failed=19 journal_blind=0 drift=1
cursor_reset=1 unknown_reasons=fold_unreadable`

- **Findings (5):**
  - `fold_unreadable` (CRITICAL, `_host`): there is no registry export yet (`evidence/registry/` does not exist), so
    the fold probe raises `unreadable`. By design the pass is UNKNOWN until AUT-5a's bootstrap exists (plan section
    3.3.2; activation says to enable the timer after the bootstrap rows exist).
  - `unit_missing` x2 (CRITICAL): `breezy-autonomy-health.service` and `.timer` (X-8 not-deployed rule; clears when the
    units are installed).
  - `unit_config_drift` (WARNING until 2026-10-16, CRITICAL from it): `breezy-trade-supervisor.service` carries the
    drop-in `fq-v1-halt-orders-off.conf`, which has no committed copy under `deploy/systemd/`. This is the
    operator's orders-off drop-in; it was not touched. A committed baseline copy is a coordinator decision before 10-16.
  - `timer_no_next_elapse` (CRITICAL): `us-source-collector@lamp.timer` shows no future elapse.
- **54 new failures from the journal** (cursor reset: no cursor exists, so the pass reads back the 2-day fallback
  window): `us-source-collector@lav` x12 and `@mos` x9 (EXIT_CODE, CRITICAL), `breezy-portfolio-roi` x2,
  `breezy-pfm-history-1008a` x2, `breezy-exit-window-study` x2 (MEMORY_CEILING_SUSPECT), `breezy-autonomy-alert-redeliver`
  x2, `breezy-fee-evidence-pull` x1 (all CRITICAL), and 24 `run-*` transients (UNRESOLVED_TRANSIENT, WARNING). A first
  enabled pass would enqueue one alert per class record (about 54 plus the findings above) unless the activation seeds
  the cursor or accepts the burst.
- **Foreign (19, never paged):** 15 `claude-aut6-<hex>` agent transients, `claude-aut6-probe-*`,
  `claude-aut6-v6-fail`, `claude-s5-focused2`, `suprestart-focused`.
- `failed_units=0`: nothing is `failed` in the live snapshot at the moment of the pass.
