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
